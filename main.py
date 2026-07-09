#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Adolf Anime Bot - Comprehensive Anime Information Bot
Developer: Mohmmad_badr
Bot: @Adolf_123_bot
Features: Search, Top, Season, Random, Favorites, Recommendations, Image Search, Quotes
"""

import os
import sys
import json
import time
import random
import sqlite3
import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

# ==================== CONFIGURATION ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# APIs - All FREE, No API Key Required!
JIKAN_BASE_URL = "https://api.jikan.moe/v4"
ANILIST_URL = "https://graphql.anilist.co"
KITSU_URL = "https://kitsu.io/api/edge"
TRACE_MOE_URL = "https://api.trace.moe/search"
ANIMECHAN_URL = "https://animechan.xyz/api"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== DATABASE ====================
DB_PATH = "anime_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            anime_id INTEGER NOT NULL,
            anime_title TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, anime_id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_prefs (
            user_id INTEGER PRIMARY KEY,
            language TEXT DEFAULT "ar",
            notifications_enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_cache (
            key TEXT PRIMARY KEY,
            data TEXT,
            expires_at TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watch_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            anime_id INTEGER NOT NULL,
            action TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()

# ==================== CACHE MANAGER ====================
class CacheManager:
    def __init__(self, ttl_minutes=30):
        self.ttl = ttl_minutes
        self.memory_cache = {}
    
    def get(self, key):
        if key in self.memory_cache:
            entry = self.memory_cache[key]
            if entry["expires"] > datetime.now():
                return entry["data"]
            del self.memory_cache[key]
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT data FROM api_cache WHERE key = ? AND expires_at > ?",
            (key, datetime.now())
        )
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return json.loads(result[0])
        return None
    
    def set(self, key, data):
        expires = datetime.now() + timedelta(minutes=self.ttl)
        self.memory_cache[key] = {"data": data, "expires": expires}
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO api_cache (key, data, expires_at) VALUES (?, ?, ?)",
            (key, json.dumps(data), expires)
        )
        conn.commit()
        conn.close()

cache = CacheManager(ttl_minutes=60)

# ==================== API CLIENT ====================
class AnimeAPIClient:
    def __init__(self):
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            headers={"User-Agent": "AdolfAnimeBot/1.0"}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def _fetch(self, url, method="GET", data=None, headers=None):
        try:
            cache_key = f"{method}:{url}:{json.dumps(data or {}, sort_keys=True)}"
            cached = cache.get(cache_key)
            if cached:
                return cached
            
            if method == "GET":
                async with self.session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        cache.set(cache_key, result)
                        return result
            elif method == "POST":
                async with self.session.post(url, json=data, headers=headers) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        cache.set(cache_key, result)
                        return result
        except Exception as e:
            logger.error(f"API Error: {e}")
        return None
    
    async def search_jikan(self, query, limit=10):
        url = f"{JIKAN_BASE_URL}/anime?q={query}&limit={limit}&order_by=popularity&sort=asc"
        result = await self._fetch(url)
        return result.get("data", []) if result else []
    
    async def get_anime_jikan(self, anime_id):
        url = f"{JIKAN_BASE_URL}/anime/{anime_id}/full"
        result = await self._fetch(url)
        return result.get("data") if result else None
    
    async def get_top_anime(self, type_filter="", limit=25):
        url = f"{JIKAN_BASE_URL}/top/anime?limit={limit}"
        if type_filter:
            url += f"&type={type_filter}"
        result = await self._fetch(url)
        return result.get("data", []) if result else []
    
    async def get_seasonal_anime(self, year=None, season=None):
        if not year or not season:
            now = datetime.now()
            year = now.year
            month = now.month
            if month in [1, 2, 3]:
                season = "winter"
            elif month in [4, 5, 6]:
                season = "spring"
            elif month in [7, 8, 9]:
                season = "summer"
            else:
                season = "fall"
        
        url = f"{JIKAN_BASE_URL}/seasons/{year}/{season}"
        result = await self._fetch(url)
        return result.get("data", []) if result else []
    
    async def get_random_anime(self):
        url = f"{JIKAN_BASE_URL}/random/anime"
        result = await self._fetch(url)
        return result.get("data") if result else None
    
    async def search_anilist(self, query, limit=10):
        graphql_query = """
        query ($search: String, $limit: Int) {
            Page(page: 1, perPage: $limit) {
                media(search: $search, type: ANIME, sort: POPULARITY_DESC) {
                    id
                    title { romaji english native }
                    coverImage { large }
                    averageScore
                    episodes
                    status
                    genres
                    description
                    studios { nodes { name } }
                }
            }
        }
        """
        result = await self._fetch(
            ANILIST_URL,
            "POST",
            {"query": graphql_query, "variables": {"search": query, "limit": limit}}
        )
        if result and "data" in result:
            return result["data"]["Page"]["media"]
        return []
    
    async def search_by_image(self, image_url):
        url = f"{TRACE_MOE_URL}?url={image_url}"
        result = await self._fetch(url)
        return result.get("result", []) if result else []
    
    async def get_random_quote(self):
        result = await self._fetch(f"{ANIMECHAN_URL}/random")
        return result

# ==================== TRANSLATION SERVICE ====================
class TranslationService:
    async def translate(self, text, target_lang="ar", source_lang="en"):
        if not text or len(text) < 3:
            return text
        
        try:
            url = f"{MYMEMORY_URL}?q={text}&langpair={source_lang}|{target_lang}"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("responseStatus") == 200:
                            return data["responseData"]["translatedText"]
        except Exception:
            pass
        
        return text

# ==================== FORMATTERS ====================
class MessageFormatter:
    @staticmethod
    def format_anime_info(data, translated_desc=None):
        if "title" in data and isinstance(data["title"], dict):
            title = data["title"].get("english") or data["title"].get("romaji") or "Unknown"
            title_jp = data["title"].get("native", "")
            score = data.get("averageScore", "N/A")
            if score != "N/A":
                score = f"{score / 10:.1f}"
            episodes = data.get("episodes", "?")
            status = data.get("status", "Unknown")
            genres = ", ".join(data.get("genres", []))
            description = data.get("description", "No description")
            studios = ", ".join([s["name"] for s in data.get("studios", {}).get("nodes", [])])
            image_url = data.get("coverImage", {}).get("large", "")
        else:
            title = data.get("title", "Unknown")
            title_jp = data.get("title_japanese", "")
            score = data.get("score", "N/A")
            episodes = data.get("episodes", "?")
            status = data.get("status", "Unknown")
            genres = ", ".join([g["name"] for g in data.get("genres", [])])
            description = data.get("synopsis", "No description")
            studios = ", ".join([s["name"] for s in data.get("studios", [])])
            image_url = data.get("images", {}).get("jpg", {}).get("large_image_url", "")
        
        description = description.replace("<br>", "\n").replace("<i>", "").replace("</i>", "")
        description = description.replace("<b>", "").replace("</b>", "")
        description = description.replace("<br/>", "\n").replace("<br />", "\n")
        
        if translated_desc:
            description = translated_desc
        
        status_map = {
            "FINISHED": "Completed",
            "RELEASING": "Ongoing",
            "NOT_YET_RELEASED": "Not Yet Aired",
            "CANCELLED": "Cancelled",
            "HIATUS": "On Hiatus",
            "Finished Airing": "Completed",
            "Currently Airing": "Ongoing",
            "Not yet aired": "Not Yet Aired"
        }
        status_en = status_map.get(status, status)
        
        message = f"""
*🎌 {title}*
"""
        if title_jp and title_jp != title:
            message += f"\n🇯🇵 `{title_jp}`\n"
        
        message += f"""
⭐ *Rating:* {score}/10
📺 *Episodes:* {episodes}
🎭 *Genres:* {genres or "Not specified"}
🏢 *Studio:* {studios or "Unknown"}
📊 *Status:* {status_en}

📖 *Synopsis:*
{description[:500]}{"..." if len(description) > 500 else ""}
"""
        return message, image_url
    
    @staticmethod
    def format_top_anime(anime_list):
        message = "🏆 *Top Anime* 🏆\n\n"
        for i, anime in enumerate(anime_list[:10], 1):
            if "title" in anime and isinstance(anime["title"], dict):
                title = anime["title"].get("english") or anime["title"].get("romaji", "Unknown")
                score = anime.get("averageScore", 0) / 10
            else:
                title = anime.get("title", "Unknown")
                score = anime.get("score", 0)
            
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
            message += f"{medal} *{title}* - ⭐ {score}\n"
        
        message += "\nClick any title for details!"
        return message
    
    @staticmethod
    def format_seasonal_anime(anime_list):
        now = datetime.now()
        month = now.month
        seasons = {1: "Winter", 2: "Winter", 3: "Winter",
                   4: "Spring", 5: "Spring", 6: "Spring",
                   7: "Summer", 8: "Summer", 9: "Summer",
                   10: "Fall", 11: "Fall", 12: "Fall"}
        season = seasons.get(month, "Current")
        
        message = f"🌸 *{season} {now.year} Anime* 🌸\n\n"
        
        for i, anime in enumerate(anime_list[:15], 1):
            if "title" in anime and isinstance(anime["title"], dict):
                title = anime["title"].get("english") or anime["title"].get("romaji", "Unknown")
            else:
                title = anime.get("title", "Unknown")
            
            message += f"{i}. *{title}*\n"
        
        return message
    
    @staticmethod
    def format_quote(quote_data):
        return f"""
💬 *Anime Quote*

"_{quote_data.get("quote", "")}_"

- *{quote_data.get("character", "Unknown")}* from *{quote_data.get("anime", "Unknown")}*
"""

# ==================== DATABASE MANAGER ====================
class DatabaseManager:
    @staticmethod
    def add_favorite(user_id, anime_id, anime_title):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO favorites (user_id, anime_id, anime_title) VALUES (?, ?, ?)",
                (user_id, anime_id, anime_title)
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    
    @staticmethod
    def remove_favorite(user_id, anime_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM favorites WHERE user_id = ? AND anime_id = ?",
            (user_id, anime_id)
        )
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_favorites(user_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT anime_id, anime_title, added_at FROM favorites WHERE user_id = ? ORDER BY added_at DESC",
            (user_id,)
        )
        results = cursor.fetchall()
        conn.close()
        return [{"anime_id": r[0], "title": r[1], "added_at": r[2]} for r in results]
    
    @staticmethod
    def is_favorite(user_id, anime_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND anime_id = ?",
            (user_id, anime_id)
        )
        result = cursor.fetchone()
        conn.close()
        return result is not None
    
    @staticmethod
    def add_to_history(user_id, anime_id, action):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO watch_history (user_id, anime_id, action) VALUES (?, ?, ?)",
            (user_id, anime_id, action)
        )
        conn.commit()
        conn.close()

# ==================== BOT COMMANDS ====================
formatter = MessageFormatter()
db = DatabaseManager()

async def start_command(update, context):
    welcome_msg = """
🎌 *Welcome to Adolf Anime Bot!* 🎌

I am a comprehensive anime information bot. I can help you with:

🔍 Search for any anime
🏆 Top rated anime list
🌸 Current season anime
🎲 Random anime
❤️ Manage favorites
🤖 Smart recommendations
📸 Image search (Trace.moe)
💬 Anime quotes

*Available Commands:*
/anime <name> - Anime information
/top - Top rated anime
/season - Current season anime
/search <name> - Advanced search
/random - Random anime
/fav - Favorites list
/quote - Random quote
/recommend - Smart recommendation
/help - Help

👨‍💻 Developer: @Mohmmad_badr
"""
    
    keyboard = [
        [InlineKeyboardButton("🔍 Search Anime", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("🏆 Top", callback_data="top"),
         InlineKeyboardButton("🌸 Season", callback_data="season")],
        [InlineKeyboardButton("🎲 Random", callback_data="random"),
         InlineKeyboardButton("❤️ Favorites", callback_data="fav")],
        [InlineKeyboardButton("💬 Quote", callback_data="quote"),
         InlineKeyboardButton("🤖 Recommend", callback_data="recommend")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_msg,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def help_command(update, context):
    help_msg = """
📚 *Bot Usage Guide* 📚

*Basic Commands:*
/anime <name> - Shows detailed anime info
/top - Shows top 10 anime
/season - Shows current season anime
/search <name> - Advanced search with options
/random - Gives you a random anime

*Additional Commands:*
/fav - View and manage favorites
/quote - Random anime quote
/recommend - Smart recommendation based on your history

*How to Search:*
• Type `/anime` followed by the anime name
• Example: `/anime Attack on Titan`
• Example: `/anime Naruto`

*Tips:*
• The bot supports both English and Japanese names
• You can send an image to search for the anime (Trace.moe)
• Use the buttons below messages for quick navigation

👨‍💻 For support: @Mohmmad_badr
"""
    await update.message.reply_text(help_msg, parse_mode=ParseMode.MARKDOWN)

async def anime_command(update, context):
    if not context.args:
        await update.message.reply_text(
            "❌ *Please enter an anime name*\n\n"
            "Example: `/anime Attack on Titan`\n"
            "Example: `/anime Naruto`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    query = " ".join(context.args)
    await update.message.reply_text(f"🔍 Searching for: *{query}*...", parse_mode=ParseMode.MARKDOWN)
    
    async with AnimeAPIClient() as client:
        jikan_results = await client.search_jikan(query, limit=5)
        anilist_results = await client.search_anilist(query, limit=5)
        
        all_results = []
        seen_ids = set()
        
        for anime in jikan_results:
            mal_id = anime.get("mal_id")
            if mal_id not in seen_ids:
                seen_ids.add(mal_id)
                all_results.append(("jikan", anime))
        
        for anime in anilist_results:
            al_id = anime.get("id")
            if al_id not in seen_ids:
                seen_ids.add(al_id)
                all_results.append(("anilist", anime))
        
        if not all_results:
            await update.message.reply_text(
                "😔 *No results found*\n\n"
                "Try:\n"
                "• Check the spelling\n"
                "• Search using English or Japanese name",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        source, first_anime = all_results[0]
        
        description = ""
        if source == "jikan":
            description = first_anime.get("synopsis", "")
        else:
            description = first_anime.get("description", "")
        
        translated_desc = None
        if description:
            try:
                translator = TranslationService()
                translated_desc = await translator.translate(description[:500], target_lang="ar")
            except Exception:
                pass
        
        msg, image_url = formatter.format_anime_info(first_anime, translated_desc)
        
        keyboard = []
        
        anime_id = first_anime.get("mal_id") or first_anime.get("id", 0)
        title = first_anime.get("title", "Unknown")
        if isinstance(title, dict):
            title = title.get("english") or title.get("romaji", "Unknown")
        
        if db.is_favorite(update.effective_user.id, anime_id):
            keyboard.append([InlineKeyboardButton("❌ Remove from Favorites", callback_data=f"unfav:{anime_id}")])
        else:
            keyboard.append([InlineKeyboardButton("❤️ Add to Favorites", callback_data=f"fav:{anime_id}:{title}")])
        
        if len(all_results) > 1:
            keyboard.append([InlineKeyboardButton("📋 More Results", callback_data=f"more:{query}")])
        
        keyboard.append([
            InlineKeyboardButton("🔍 MyAnimeList", url=f"https://myanimelist.net/anime/{anime_id}"),
            InlineKeyboardButton("🌐 AniList", url=f"https://anilist.co/anime/{anime_id}")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if image_url:
            try:
                await update.message.reply_photo(
                    photo=image_url,
                    caption=msg,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
            except Exception:
                await update.message.reply_text(
                    msg,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
        else:
            await update.message.reply_text(
                msg,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
        
        db.add_to_history(update.effective_user.id, anime_id, "search")

async def top_command(update, context):
    await update.message.reply_text("🏆 Fetching top anime...")
    
    async with AnimeAPIClient() as client:
        results = await client.get_top_anime(limit=10)
        
        if not results:
            await update.message.reply_text("❌ Error, try again later.")
            return
        
        msg = formatter.format_top_anime(results)
        
        keyboard = []
        for anime in results[:5]:
            anime_id = anime.get("mal_id", 0)
            title = anime.get("title", "Unknown")
            keyboard.append([InlineKeyboardButton(title, callback_data=f"anime:{anime_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def season_command(update, context):
    await update.message.reply_text("🌸 Fetching current season anime...")
    
    async with AnimeAPIClient() as client:
        results = await client.get_seasonal_anime()
        
        if not results:
            await update.message.reply_text("❌ Error, try again later.")
            return
        
        msg = formatter.format_seasonal_anime(results)
        
        keyboard = []
        for anime in results[:10]:
            if "title" in anime and isinstance(anime["title"], dict):
                title = anime["title"].get("english") or anime["title"].get("romaji", "Unknown")
                anime_id = anime.get("id", 0)
            else:
                title = anime.get("title", "Unknown")
                anime_id = anime.get("mal_id", 0)
            
            keyboard.append([InlineKeyboardButton(title, callback_data=f"anime:{anime_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def random_command(update, context):
    await update.message.reply_text("🎲 Choosing a random anime...")
    
    async with AnimeAPIClient() as client:
        anime = await client.get_random_anime()
        
        if not anime:
            await update.message.reply_text("❌ Error, try again.")
            return
        
        description = anime.get("synopsis", "")
        translated_desc = None
        if description:
            try:
                translator = TranslationService()
                translated_desc = await translator.translate(description[:500], target_lang="ar")
            except Exception:
                pass
        
        msg, image_url = formatter.format_anime_info(anime, translated_desc)
        
        anime_id = anime.get("mal_id", 0)
        title = anime.get("title", "Unknown")
        
        keyboard = [
            [InlineKeyboardButton("🔄 Another Random", callback_data="random")],
            [InlineKeyboardButton("❤️ Add to Favorites", callback_data=f"fav:{anime_id}:{title}")],
            [InlineKeyboardButton("🔍 MyAnimeList", url=f"https://myanimelist.net/anime/{anime_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if image_url:
            try:
                await update.message.reply_photo(
                    photo=image_url,
                    caption=msg,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
            except Exception:
                await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        else:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def search_command(update, context):
    if not context.args:
        await update.message.reply_text(
            "❌ *Please enter a search term*\n\nExample: `/search Naruto`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    query = " ".join(context.args)
    await update.message.reply_text(f"🔍 Advanced search for: *{query}*...", parse_mode=ParseMode.MARKDOWN)
    
    async with AnimeAPIClient() as client:
        jikan_results = await client.search_jikan(query, limit=10)
        anilist_results = await client.search_anilist(query, limit=10)
        
        if not jikan_results and not anilist_results:
            await update.message.reply_text("😔 No results found.")
            return
        
        msg = f"📋 *Search results for: {query}*\n\n"
        keyboard = []
        
        for i, anime in enumerate(jikan_results[:10], 1):
            anime_id = anime.get("mal_id", 0)
            title = anime.get("title", "Unknown")
            score = anime.get("score", "N/A")
            msg += f"{i}. *{title}* - ⭐ {score}\n"
            keyboard.append([InlineKeyboardButton(f"{i}. {title}", callback_data=f"anime:{anime_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def fav_command(update, context):
    user_id = update.effective_user.id
    favorites = db.get_favorites(user_id)
    
    if not favorites:
        await update.message.reply_text(
            "❤️ *Favorites list is empty*\n\n"
            "Use `/anime <name>` then click Add to Favorites",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    msg = "❤️ *Your Favorites* ❤️\n\n"
    keyboard = []
    
    for i, fav in enumerate(favorites, 1):
        msg += f"{i}. *{fav["title"]}*\n"
        keyboard.append([
            InlineKeyboardButton(f"📺 {fav["title"]}", callback_data=f"anime:{fav["anime_id"]}"),
            InlineKeyboardButton("❌", callback_data=f"unfav:{fav["anime_id"]}")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def quote_command(update, context):
    async with AnimeAPIClient() as client:
        quote = await client.get_random_quote()
        
        if quote:
            msg = formatter.format_quote(quote)
            keyboard = [[InlineKeyboardButton("🔄 Another Quote", callback_data="quote")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        else:
            await update.message.reply_text("❌ Could not fetch quote, try again.")

async def recommend_command(update, context):
    user_id = update.effective_user.id
    
    await update.message.reply_text("🤖 Analyzing your preferences and generating a smart recommendation...")
    
    favorites = db.get_favorites(user_id)
    
    async with AnimeAPIClient() as client:
        if favorites:
            genres = set()
            for fav in favorites[:3]:
                try:
                    anime_data = await client.get_anime_jikan(fav["anime_id"])
                    if anime_data:
                        for genre in anime_data.get("genres", []):
                            genres.add(genre["name"])
                except Exception:
                    continue
            
            if genres:
                genre_query = random.choice(list(genres))
                results = await client.search_jikan(genre_query, limit=20)
                
                fav_ids = {f["anime_id"] for f in favorites}
                recommendations = [r for r in results if r.get("mal_id") not in fav_ids]
                
                if recommendations:
                    rec = random.choice(recommendations[:10])
                    
                    description = rec.get("synopsis", "")
                    translated_desc = None
                    if description:
                        try:
                            translator = TranslationService()
                            translated_desc = await translator.translate(description[:500], target_lang="ar")
                        except Exception:
                            pass
                    
                    msg, image_url = formatter.format_anime_info(rec, translated_desc)
                    
                    anime_id = rec.get("mal_id", 0)
                    title = rec.get("title", "Unknown")
                    
                    keyboard = [
                        [InlineKeyboardButton("❤️ Add to Favorites", callback_data=f"fav:{anime_id}:{title}")],
                        [InlineKeyboardButton("🔄 Another Recommendation", callback_data="recommend")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    header = "🤖 *Smart Recommendation for You* 🤖\n\n"
                    header += "Based on your favorites, I think you will like this:\n\n"
                    
                    if image_url:
                        try:
                            await update.message.reply_photo(
                                photo=image_url,
                                caption=header + msg,
                                parse_mode=ParseMode.MARKDOWN,
                                reply_markup=reply_markup
                            )
                        except Exception:
                            await update.message.reply_text(header + msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
                    else:
                        await update.message.reply_text(header + msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
                    return
        
        # Fallback: random top anime
        results = await client.get_top_anime(limit=50)
        if results:
            rec = random.choice(results[:20])
            
            description = rec.get("synopsis", "")
            translated_desc = None
            if description:
                try:
                    translator = TranslationService()
                    translated_desc = await translator.translate(description[:500], target_lang="ar")
                except Exception:
                    pass
            
            msg, image_url = formatter.format_anime_info(rec, translated_desc)
            
            anime_id = rec.get("mal_id", 0)
            title = rec.get("title", "Unknown")
            
            keyboard = [
                [InlineKeyboardButton("❤️ Add to Favorites", callback_data=f"fav:{anime_id}:{title}")],
                [InlineKeyboardButton("🔄 Another Recommendation", callback_data="recommend")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            header = "🤖 *Smart Recommendation* 🤖\n\n"
            header += "This is one of the best anime, give it a try:\n\n"
            
            if image_url:
                try:
                    await update.message.reply_photo(
                        photo=image_url,
                        caption=header + msg,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=reply_markup
                    )
                except Exception:
                    await update.message.reply_text(header + msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
            else:
                await update.message.reply_text(header + msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

# ==================== CALLBACK HANDLER ====================
async def button_callback(update, context):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = update.effective_user.id
    
    if data.startswith("anime:"):
        anime_id = int(data.split(":")[1])
        async with AnimeAPIClient() as client:
            anime = await client.get_anime_jikan(anime_id)
            if anime:
                description = anime.get("synopsis", "")
                translated_desc = None
                if description:
                    try:
                        translator = TranslationService()
                        translated_desc = await translator.translate(description[:500], target_lang="ar")
                    except Exception:
                        pass
                
                msg, image_url = formatter.format_anime_info(anime, translated_desc)
                
                title = anime.get("title", "Unknown")
                
                keyboard = []
                if db.is_favorite(user_id, anime_id):
                    keyboard.append([InlineKeyboardButton("❌ Remove from Favorites", callback_data=f"unfav:{anime_id}")])
                else:
                    keyboard.append([InlineKeyboardButton("❤️ Add to Favorites", callback_data=f"fav:{anime_id}:{title}")])
                
                keyboard.append([
                    InlineKeyboardButton("🔍 MyAnimeList", url=f"https://myanimelist.net/anime/{anime_id}"),
                    InlineKeyboardButton("🌐 AniList", url=f"https://anilist.co/anime/{anime_id}")
                ])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                try:
                    if image_url:
                        await query.message.reply_photo(
                            photo=image_url,
                            caption=msg,
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=reply_markup
                        )
                    else:
                        await query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
                except Exception:
                    await query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
            else:
                await query.message.reply_text("❌ Could not fetch anime info.")
    
    elif data.startswith("fav:"):
        parts = data.split(":", 2)
        anime_id = int(parts[1])
        title = parts[2] if len(parts) > 2 else "Unknown"
        
        if db.add_favorite(user_id, anime_id, title):
            await query.answer("✅ Added to favorites!")
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Remove from Favorites", callback_data=f"unfav:{anime_id}")],
                    [InlineKeyboardButton("🔍 MyAnimeList", url=f"https://myanimelist.net/anime/{anime_id}")]
                ])
            )
        else:
            await query.answer("⚠️ Already in favorites!")
    
    elif data.startswith("unfav:"):
        anime_id = int(data.split(":")[1])
        db.remove_favorite(user_id, anime_id)
        await query.answer("❌ Removed from favorites!")
        await query.message.delete()
        await fav_command(update, context)
    
    elif data == "top":
        await top_command(update, context)
    
    elif data == "season":
        await season_command(update, context)
    
    elif data == "random":
        await random_command(update, context)
    
    elif data == "fav":
        await fav_command(update, context)
    
    elif data == "quote":
        await quote_command(update, context)
    
    elif data == "recommend":
        await recommend_command(update, context)
    
    elif data.startswith("more:"):
        query_text = data.split(":", 1)[1]
        await query.message.reply_text(f"🔍 Fetching more results...")
        async with AnimeAPIClient() as client:
            results = await client.search_jikan(query_text, limit=10)
            if results:
                msg = f"📋 *More Results*\n\n"
                keyboard = []
                for i, anime in enumerate(results[1:6], 2):
                    anime_id = anime.get("mal_id", 0)
                    title = anime.get("title", "Unknown")
                    keyboard.append([InlineKeyboardButton(f"{i}. {title}", callback_data=f"anime:{anime_id}")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

# ==================== PHOTO HANDLER ====================
async def photo_handler(update, context):
    photo = update.message.photo[-1]
    file = await photo.get_file()
    
    await update.message.reply_text("📸 Searching for the anime in the image...")
    
    async with AnimeAPIClient() as client:
        results = await client.search_by_image(file.file_path)
        
        if results:
            best_match = results[0]
            anime_name = best_match.get("anilist", {}).get("title", {}).get("romaji", "Unknown")
            episode = best_match.get("episode", "?")
            similarity = best_match.get("similarity", 0) * 100
            timestamp = best_match.get("from", 0)
            
            minutes = int(timestamp // 60)
            seconds = int(timestamp % 60)
            
            msg = f"""
🎯 *Image Search Result*

🎌 *Anime:* {anime_name}
📺 *Episode:* {episode}
⏱️ *Timestamp:* {minutes}:{seconds:02d}
🎯 *Match:* {similarity:.1f}%

[🎥 Watch Scene]({best_match.get("video", "")})
"""
            
            image_url = best_match.get("image", "")
            if image_url:
                await update.message.reply_photo(photo=image_url, caption=msg, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(
                "😔 *Could not identify the anime*\n\n"
                "Tips:\n"
                "• Make sure the image is clear\n"
                "• Try a screenshot from the episode itself\n"
                "• Images from opening/ending may not be recognized",
                parse_mode=ParseMode.MARKDOWN
            )

# ==================== ERROR HANDLER ====================
async def error_handler(update, context):
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ *An unexpected error occurred*\n\n"
            "Try again, or contact @Mohmmad_badr",
            parse_mode=ParseMode.MARKDOWN
        )

# ==================== MAIN ====================
def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set!")
        print("Steps:")
        print("   1. Edit BOT_TOKEN in the code")
        print("   2. Or run with: export BOT_TOKEN=your_token")
        print("\nGet token from @BotFather on Telegram")
        sys.exit(1)
    
    init_db()
    print("Database initialized")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("anime", anime_command))
    application.add_handler(CommandHandler("top", top_command))
    application.add_handler(CommandHandler("season", season_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("random", random_command))
    application.add_handler(CommandHandler("fav", fav_command))
    application.add_handler(CommandHandler("quote", quote_command))
    application.add_handler(CommandHandler("recommend", recommend_command))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_error_handler(error_handler)
    
    print("Adolf Anime Bot is running...")
    print("Developer: @Mohmmad_badr")
    print("Bot: @Adolf_123_bot")
    print("Press Ctrl+C to stop")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

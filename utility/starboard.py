"""
Copyright 2022-present fretgfr, HumbleToS

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from __future__ import annotations

"""
INCOMPLETE
    TODO:
        - Handle message edits
        - Handle message deletes
        - Cooldown for updating the status of a message so it can't be spammed on and off?
        - Ensure error handling is correct

This module uses the following third party libs installed via pip: asqlite (https://github.com/Rapptz/asqlite)
"""

import asyncio
import logging
from dataclasses import dataclass

import asqlite
import discord
from discord.ext import commands

DB_FILENAME = "starboard.sqlite"

STARBOARD_SETUP_SQL = """
CREATE TABLE IF NOT EXISTS starredmessage (
    message_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    guild_id INTEGER,
    stars INTEGER,
    starboard_message_id INTEGER NULL DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS starboardguild (
    id INTEGER PRIMARY KEY,
    starboard_channel_id INTEGER,
    stars_required INTEGER
);
"""

_logger = logging.getLogger(__name__)

@dataclass(slots=True)
class StarredMessage:
    message_id: int
    channel_id: int
    guild_id: int
    stars: int
    starboard_message_id: int | None

    @classmethod
    async def create_or_increment(cls, *, message_id: int, channel_id: int, guild_id: int, initial_stars: int = 1, starboard_message_id: int | None = None) -> StarredMessage:
        async with asqlite.connect(DB_FILENAME) as db:
            async with db.cursor() as cur:
                await cur.execute("""
                INSERT INTO starredmessage (message_id, channel_id, guild_id, stars, starboard_message_id)
                VALUES (?, ?, ?, ?, ?) ON CONFLICT(message_id) DO UPDATE SET stars = stars + 1 RETURNING *
                """, message_id, channel_id, guild_id, initial_stars, starboard_message_id)

                await db.commit()

                res = await cur.fetchone()

                return cls(**dict(res))

    @classmethod
    async def decrement_or_ignore(cls, message_id: int, /) -> StarredMessage | None:
        async with asqlite.connect(DB_FILENAME) as db:
            async with db.cursor() as cur:
                await cur.execute("UPDATE starredmessage SET stars = stars - 1 WHERE message_id = ? RETURNING *", message_id)

                await db.commit()

                res = await cur.fetchone()

                return cls(**dict(res)) if res is not None else None

    @classmethod
    async def get_by_message_id(cls, message_id: int, /) -> StarredMessage | None:
        async with asqlite.connect(DB_FILENAME) as db:
            async with db.cursor() as cur:
                await cur.execute("SELECT * FROM starredmessage WHERE message_id = ?", message_id)

                res = await cur.fetchone()

                return cls(**dict(res)) if res is not None else None

    async def update_starboard_message_id(self, starboard_message_id: int | None, /) -> StarredMessage:
        async with asqlite.connect(DB_FILENAME) as db:
            async with db.cursor() as cur:
                await cur.execute("UPDATE starredmessage SET starboard_message_id = ? WHERE message_id = ?", starboard_message_id, self.message_id)

                await db.commit()

                self.starboard_message_id = starboard_message_id

                return self

    async def embed(self, bot: commands.Bot, /) -> discord.Embed:
        channel = bot.get_channel(self.channel_id)


        embed = discord.Embed(title="This is a test", description="this is a test")

        return embed


@dataclass(slots=True)
class StarboardGuild:
    id: int
    starboard_channel_id: int
    stars_required: int

    @classmethod
    async def setup(cls, *, _id: int, starboard_channel_id: int, stars_required: int) -> StarboardGuild:
        async with asqlite.connect(DB_FILENAME) as db:
            async with db.cursor() as cur:
                await cur.execute("""INSERT INTO starboardguild (id, starboard_channel_id, stars_required)
                VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET starboard_channel_id = ?, stars_required = ? RETURNING *""",
                _id, starboard_channel_id, stars_required, starboard_channel_id, stars_required)

                await db.commit()

                res = await cur.fetchone()

                return cls(**dict(res))

    @classmethod
    async def get_or_none(cls, _id: int, /) -> StarboardGuild | None:
        async with asqlite.connect(DB_FILENAME) as db:
            async with db.cursor() as cur:
                await cur.execute("SELECT * FROM starboardguild WHERE id = ?", _id)

                res = await cur.fetchone()

                return cls(**dict(res)) if res is not None else None

    async def update_channel_id(self, new_channel_id: int, /) -> StarboardGuild:
        async with asqlite.connect(DB_FILENAME) as db:
            async with db.cursor() as cur:
                await cur.execute("UPDATE starboardguild SET starboard_channel_id = ? WHERE id = ? RETURNING *", new_channel_id, self.id)

                await db.commit()

                self.starboard_channel_id = new_channel_id

                return self

    async def update_required_stars(self, new_stars_required: int, /) -> StarboardGuild:
        async with asqlite.connect(DB_FILENAME) as db:
            async with db.cursor() as cur:
                await cur.execute("UPDATE starboardguild SET stars_required = ? WHERE id = ? RETURNING *", new_stars_required, self.id)

                await db.commit()

                self.stars_required = new_stars_required

                return self


class StarboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # \U00002b50 -> ⭐️
        self.STAR_EMOJI = "\U00002b50"

    async def cog_load(self) -> None:
        async with asqlite.connect(DB_FILENAME) as db:
            await db.executescript(STARBOARD_SETUP_SQL)

    @commands.Cog.listener(name="on_raw_reaction_add")
    async def starboard_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if not payload.guild_id: return
        if not str(payload.emoji) == self.STAR_EMOJI: return

        sg = await StarboardGuild.get_or_none(payload.guild_id)

        if sg is None:
            return

        sm = await StarredMessage.create_or_increment(message_id=payload.message_id, channel_id=payload.channel_id, guild_id=payload.guild_id)

        if sm.stars >= sg.stars_required:
            channel = self.bot.get_guild(payload.guild_id).get_channel(sg.starboard_channel_id)

            if not channel:
                _logger.error(f"Invalid channel id for guild {payload.guild_id}")
                return

            embed = await sm.embed(self.bot)

            if sm.starboard_message_id is None:
                try:
                    msg = await channel.send(embed=embed) # TODO
                except (discord.HTTPException, discord.Forbidden):
                    _logger.error(f"Could not send message in {channel.id=}")
                    return

                await sm.update_starboard_message_id(msg.id)


    @commands.Cog.listener(name="on_raw_reaction_remove")
    async def starboard_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if not payload.guild_id: return
        if not str(payload.emoji) == self.STAR_EMOJI: return

        sg = await StarboardGuild.get_or_none(payload.guild_id)

        if sg is None:
            return

        sm = await StarredMessage.decrement_or_ignore(payload.message_id)

        if sm is None:
            return

        if sm.stars < sg.stars_required and sm.starboard_message_id is not None:
            pm = self.bot.get_guild(payload.guild_id).get_channel(sg.starboard_channel_id).get_partial_message(sm.starboard_message_id)
            await pm.delete()
            await sm.update_starboard_message_id(None)


    @commands.Cog.listener(name="on_raw_message_delete")
    async def starboard_reaction(self, payload: discord.RawMessageDeleteEvent) -> None:
        # remove that cool data from the message_id in the db
        if not payload.guild_id: return


    @commands.Cog.listener(name="on_raw_message_edit")
    async def starboard_reaction(self, payload: discord.RawMessageUpdateEvent) -> None:
        # idk, maybe remove that data as well?
        if not payload.guild_id: return


    @commands.group()
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def starboard(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @starboard.command()
    async def setup(self, ctx: commands.Context, channel: discord.TextChannel, required_stars: int) -> None:
        await StarboardGuild.setup(_id=ctx.guild.id, starboard_channel_id=channel.id, stars_required=required_stars)

        await ctx.send("Starboard is now setup.")

    @starboard.command()
    async def config(self, ctx: commands.Context, channel: discord.TextChannel = None, required_stars: int = None) -> None:

        current = await StarboardGuild.get_or_none(ctx.guild.id)

        if not current:
            await ctx.send("Starboard has not been set up, please use the `setup` command.")
            return

        if channel is not None:
            await current.update_channel_id(channel.id)

        if required_stars is not None:
            required_stars = max(min(required_stars, 50), 1) # CLAMP
            await current.update_required_stars(required_stars)

        await ctx.send("Settings updated.")


async def setup(bot: commands.Bot):
    _logger.info("Loading cog StarboardCog")
    await bot.add_cog(StarboardCog(bot))

async def teardown(_: commands.Bot):
    _logger.info("Unloading cog StarboardCog")
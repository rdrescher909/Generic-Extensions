"""
Copyright 2022-present fretgfr

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

import logging
import traceback
from abc import ABC, abstractmethod
from typing import Generic, List, Optional, TypeVar, Any, Dict

import discord
from discord.ext import commands

T = TypeVar('T')

_logger = logging.getLogger(__name__)

class ToPageModal(discord.ui.Modal, title="Go to page...t"):
    new_page = discord.ui.TextInput(label="Page", placeholder="What page are we going to?", min_length=1) # type: ignore

    def __init__(self, *, max_pages: Optional[int]) -> None:
        super().__init__()
        _logger.debug(f"Creating new ToPageModal with {max_pages=}")
        if max_pages is not None:
            pages_str = str(max_pages)
            self.new_page.placeholder = f"Enter a number between 1 and {pages_str}"
            self.new_page.max_length = len(pages_str)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.interaction = interaction
        self.stop()

class BasePaginatorView(ABC, Generic[T], discord.ui.View):
    """A base class for Paginator Views, you'll need to override some methods with your own behavior"""
    def __init__(self, *, owner: discord.Member | discord.User, pages: List[T], timeout: float = 30.0) -> None:
        super().__init__(timeout=timeout)
        assert len(pages) > 0
        self.message: discord.Message | None = None # should be set when the paginator is sent.
        self.owner = owner
        self.pages = pages
        self.max_index = len(pages) - 1 # List indecies
        self.current_index = 0

        self._update_state()

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.NotFound:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        """coro for handing errors in this paginator. By default logs the error's traceback

        By default logs the error, but can be overridden for custom behavior.

        Parameters
        ----------
        interaction : discord.Interaction
            The interaction that errored
        error : Exception
            The error that occured
        item : discord.ui.Item
            The item that generated this error.
        """
        user_id = interaction.user.id
        trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))

        _logger.error(f"Ignoring exception in Paginator owned by: {user_id=}")
        _logger.error(trace)

        if interaction.response.is_done():
            await interaction.followup.send("An unexpected error occured.", ephemeral=True)

        else:
            await interaction.response.send_message("An unexpected error occured.", ephemeral=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """coro that "checks" an interaction on this paginator.

        By default allows only the owner to interact, however you can override this for custom behavior.

        Parameters
        ----------
        interaction : discord.Interaction
            The interaction on the view.

        Returns
        -------
        bool
            True to propagate the interaction, False to not.

            If you do not respond to an ignored interaction, it will error on the users display,
            it's recommeded to respond with an error message.
        """
        if interaction.user.id == self.owner.id:
            return True
        await interaction.response.send_message(f"This paginator belongs to {self.owner.mention}.", ephemeral=True)
        return False

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.gray, disabled=True)
    async def to_first_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.current_index = 0
        await self.update(interaction)

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.green, disabled=True)
    async def back_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.current_index >= 1:
            self.current_index -= 1
        await self.update(interaction)

    @discord.ui.button(label="1", style=discord.ButtonStyle.blurple, disabled=True)
    async def count_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        # Should never be called. Just defer in case it gets called.
        await interaction.response.defer()

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.green)
    async def fwd_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.current_index < self.max_index:
            self.current_index += 1
        await self.update(interaction)

    @discord.ui.button(emoji="⏭️", style= discord.ButtonStyle.gray)
    async def to_last_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.current_index = self.max_index
        await self.update(interaction)

    @discord.ui.button(label="Go To Page...", style=discord.ButtonStyle.blurple)
    async def goto_modal(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.message is None:
            return

        modal = ToPageModal(max_pages=self.max_index + 1) # Their index is one higher than ours.
        await interaction.response.send_modal(modal)
        timed_out = await modal.wait()

        if timed_out:
            await interaction.followup.send('Took too long', ephemeral=True)
            return
        elif self.is_finished():
            await modal.interaction.response.send_message('Took too long', ephemeral=True)
            return

        value = str(modal.new_page.value)
        if not value.isdigit():
            await modal.interaction.response.send_message(f'Expected a number not {value!r}', ephemeral=True)
            return

        value = int(value)
        if not 0 < value <= self.max_index + 1:
            if not modal.interaction.response.is_done():
                error = modal.new_page.placeholder.replace("Enter", "Expected") # type: ignore
                await modal.interaction.response.send_message(error, ephemeral=True)
                return

        self.current_index = value - 1 # Our index is one lower than theirs
        await self.update(modal.interaction)

    @discord.ui.button(label="Quit", style=discord.ButtonStyle.red)
    async def stop_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            await self.on_stop(interaction)
        except NotImplementedError:
            await interaction.response.edit_message(view=None)
        self.stop()

    def _update_state(self) -> None:
        _logger.debug(f"{self!r} _update called.")
        # Disable unusable buttons
        if self.current_index == self.max_index:
            self.fwd_btn.style = discord.ButtonStyle.grey
            self.fwd_btn.disabled = True
            self.to_last_btn.disabled = True
        else:
            self.fwd_btn.style = discord.ButtonStyle.green
            self.fwd_btn.disabled = False
            self.to_last_btn.disabled = False

        if self.current_index == 0:
            self.back_btn.style = discord.ButtonStyle.grey
            self.back_btn.disabled = True
            self.to_first_btn.disabled = True
        else:
            self.back_btn.style = discord.ButtonStyle.green
            self.back_btn.disabled = False
            self.to_first_btn.disabled = False

        self.count_btn.label = f"{self.current_index + 1}/{len(self.pages)}" # Start at 1 instead of 0.

    async def update(self, interaction: discord.Interaction) -> None:
        self._update_state()
        await self.show_page(interaction)

    @property
    def current_page(self) -> T:
        return self.pages[self.current_index]

    @classmethod
    async def start(cls, ctx_or_interaction: commands.Context[commands.Bot] | discord.Interaction, /, owner: discord.Member | discord.User, pages: List[T], timeout: float = 30.0) -> BasePaginatorView[T]:
        """A method that creates and starts the paginator

        Parameters
        ----------
        ctx : commands.Context
            The context to start in
        owner : discord.Member | discord.User
            The owner of the paginator
        pages : List[Any]
            The page data for this paginator
        timeout : float, optional
            The paginator timeout, by default 30.0
        """
        view = cls(owner=owner, pages=pages, timeout=timeout)
        initial = await view.format_page()

        args: List[str] = []
        kwargs: Dict[str, Any] = {"view": view}

        if isinstance(initial, discord.Embed):
            kwargs["embed"] = initial
        else:
            args.append(initial)

        if isinstance(ctx_or_interaction, commands.Context):
            view.message = await ctx_or_interaction.send(*args, **kwargs)
        else:
            if ctx_or_interaction.response.is_done():
                view.message = await ctx_or_interaction.followup.send(*args, **kwargs, wait=True)
            else:
                await ctx_or_interaction.response.send_message(*args, **kwargs)
                view.message = await ctx_or_interaction.original_response()

        return view

    @abstractmethod
    async def format_page(self, **kwargs: Dict[str, Any]) -> Any:
        """This coro is responsible for formating the page data, the resulting information can be used in show_page

        Returns
        -------
        Any
            A formatted page for `show_page` to use, typically a `discord.Embed`

        Raises
        ------
        NotImplementedError
            You have not changed this method.
        """
        ...

    @abstractmethod
    async def show_page(self, interaction: discord.Interaction) -> None:
        """This function is responsible for two things, it needs to perform the showing
        of the next page, and update the view on the message as well
        likely through `interaction.response.edit_message
        (i.e. interaction.response.edit_message(embed=new_embed, view=self))
        current page data is accessed via `self.current_page` or a `self.format_page` coro if you've overwritten it.

        Parameters
        ----------
        interaction : discord.Interaction
            The interaction to respond to
        """
        ...

    @abstractmethod
    async def on_stop(self, interaction: discord.Interaction) -> None:
        """Perform any behavior you'd like when someone hits the stop button
        By default this just edits the message to remove the view.
        However you could make it do whatever you want, like disabling the children.

        Parameters
        ----------
        interaction : discord.Interaction
            The interaction that triggered the stop
        """
        ...


class EmbedPaginator(BasePaginatorView[discord.Embed]):
    async def format_page(self) -> discord.Embed:
        return self.current_page

    async def show_page(self, interaction: discord.Interaction) -> None:
        current_page = await self.format_page()
        await interaction.response.edit_message(embed=current_page, view=self)

    async def on_stop(self, interaction: discord.Interaction) -> None:
        return await super().on_stop(interaction)

"""Discord UI views and modals for private voice calls."""

from __future__ import annotations

import discord

from bot.utils.private_voice_manager import PrivateVoiceManager


class PrivateVoiceInviteLinkView(discord.ui.View):
    """DM view with a direct link to join the private call."""

    def __init__(self, channel: discord.VoiceChannel) -> None:
        """Initialize the invite link view."""

        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Entrar na call",
                style=discord.ButtonStyle.link,
                url=f"https://discord.com/channels/{channel.guild.id}/{channel.id}",
            ),
        )


class PrivateVoiceUserLimitModal(discord.ui.Modal):
    """Modal that updates the call user limit."""

    def __init__(
        self,
        *,
        manager: PrivateVoiceManager,
        channel: discord.VoiceChannel,
    ) -> None:
        """Initialize the user limit modal."""

        super().__init__(title="Definir limite de usuários")
        self.manager = manager
        self.channel = channel
        self.limit_input: discord.ui.TextInput[PrivateVoiceUserLimitModal] = (
            discord.ui.TextInput(
                label="Limite",
                placeholder="Use 0 para remover o limite",
                min_length=1,
                max_length=2,
                required=True,
            )
        )
        self.add_item(self.limit_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Persist the requested user limit."""

        try:
            limit = self.manager.validate_user_limit(str(self.limit_input.value))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await self.manager.set_user_limit(channel=self.channel, limit=limit)
        await interaction.response.send_message(
            f"Limite da call atualizado para {limit}.",
            ephemeral=True,
        )


class PrivateVoiceRenameModal(discord.ui.Modal):
    """Modal that renames the private call."""

    def __init__(
        self,
        *,
        manager: PrivateVoiceManager,
        channel: discord.VoiceChannel,
    ) -> None:
        """Initialize the rename modal."""

        super().__init__(title="Renomear call")
        self.manager = manager
        self.channel = channel
        self.name_input: discord.ui.TextInput[PrivateVoiceRenameModal] = (
            discord.ui.TextInput(
                label="Novo nome",
                placeholder="Ex.: Call Privada - Squad",
                min_length=1,
                max_length=100,
                required=True,
            )
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Rename the private call."""

        new_name = self.manager.sanitize_channel_name(str(self.name_input.value))
        await self.manager.rename_call(channel=self.channel, name=new_name)
        await interaction.response.send_message(
            f"Call renomeada para **{new_name}**.",
            ephemeral=True,
        )


class PrivateVoiceInviteSelect(discord.ui.UserSelect[discord.ui.View]):
    """User selector that sends a private voice call invite."""

    def __init__(
        self,
        *,
        manager: PrivateVoiceManager,
        channel: discord.VoiceChannel,
        owner: discord.Member,
    ) -> None:
        """Initialize the invite selector."""

        super().__init__(
            placeholder="Selecione um usuário para convidar",
            min_values=1,
            max_values=1,
        )
        self.manager = manager
        self.channel = channel
        self.owner = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        """Send the selected member a DM invite."""

        target = self.values[0]
        if not isinstance(target, discord.Member):
            await interaction.response.send_message(
                "Não foi possível identificar esse usuário no servidor.",
                ephemeral=True,
            )
            return

        invite_view = PrivateVoiceInviteLinkView(self.channel)
        sent = await self.manager.invite_member(
            owner=self.owner,
            target=target,
            channel=self.channel,
            invite_view=invite_view,
        )
        if not sent:
            await interaction.response.send_message(
                "Convite liberado, mas não consegui enviar DM para esse usuário.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Convite enviado para {target.mention}.",
            ephemeral=True,
        )


class PrivateVoiceInvitePickerView(discord.ui.View):
    """Ephemeral view that lets the owner choose a member to invite."""

    def __init__(
        self,
        *,
        manager: PrivateVoiceManager,
        channel: discord.VoiceChannel,
        owner: discord.Member,
    ) -> None:
        """Initialize the invite picker."""

        super().__init__(timeout=60)
        self.manager = manager
        self.channel = channel
        self.owner = owner
        self.add_item(
            PrivateVoiceInviteSelect(
                manager=manager,
                channel=channel,
                owner=owner,
            ),
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Allow only the call owner to use the invite picker."""

        if interaction.user.id == self.owner.id:
            return True

        await interaction.response.send_message(
            "Apenas o dono da call pode usar esse convite.",
            ephemeral=True,
        )
        return False


class PrivateVoiceControlView(discord.ui.View):
    """Persistent controls for a temporary private voice call."""

    def __init__(
        self,
        *,
        manager: PrivateVoiceManager,
        channel: discord.VoiceChannel,
        owner: discord.Member,
    ) -> None:
        """Initialize private call controls."""

        super().__init__(timeout=None)
        self.manager = manager
        self.channel = channel
        self.owner = owner

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Allow only the private call owner to use the controls."""

        if self.manager.is_owner(
            channel_id=self.channel.id,
            user_id=interaction.user.id,
        ):
            return True

        await interaction.response.send_message(
            "Apenas o dono da call pode configurar esta call.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(
        label="👥 Definir Limite de Usuários",
        style=discord.ButtonStyle.primary,
        custom_id="private_voice:set_limit",
    )
    async def set_limit(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        """Open the user limit modal."""

        await interaction.response.send_modal(
            PrivateVoiceUserLimitModal(manager=self.manager, channel=self.channel),
        )

    @discord.ui.button(
        label="📨 Convidar Usuário",
        style=discord.ButtonStyle.primary,
        custom_id="private_voice:invite_user",
    )
    async def invite_user(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        """Open the invite user selector."""

        await interaction.response.send_message(
            "Selecione o usuário que receberá o convite por DM.",
            view=PrivateVoiceInvitePickerView(
                manager=self.manager,
                channel=self.channel,
                owner=self.owner,
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="🔒 Alterar Visibilidade",
        style=discord.ButtonStyle.secondary,
        custom_id="private_voice:toggle_visibility",
    )
    async def toggle_visibility(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        """Toggle public/private visibility for the call."""

        is_private = await self.manager.toggle_visibility(channel=self.channel)
        status = "privada" if is_private else "visível para o servidor"
        await interaction.response.send_message(
            f"A call agora está {status}.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="🎤 Soundboard (Ativar/Desativar)",
        style=discord.ButtonStyle.secondary,
        custom_id="private_voice:toggle_soundboard",
    )
    async def toggle_soundboard(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        """Toggle soundboard usage."""

        enabled = await self.manager.toggle_soundboard(channel=self.channel)
        status = "ativado" if enabled else "desativado"
        await interaction.response.send_message(
            f"Soundboard {status}.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="📺 Screen Share (Ativar/Desativar)",
        style=discord.ButtonStyle.secondary,
        custom_id="private_voice:toggle_screen_share",
    )
    async def toggle_screen_share(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        """Toggle screen sharing."""

        enabled = await self.manager.toggle_screen_share(channel=self.channel)
        status = "ativado" if enabled else "desativado"
        await interaction.response.send_message(
            f"Screen share {status}.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="🔄 Renomear Call",
        style=discord.ButtonStyle.secondary,
        custom_id="private_voice:rename",
    )
    async def rename_call(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        """Open the call rename modal."""

        await interaction.response.send_modal(
            PrivateVoiceRenameModal(manager=self.manager, channel=self.channel),
        )

    @discord.ui.button(
        label="🗑️ Deletar Call Agora",
        style=discord.ButtonStyle.danger,
        custom_id="private_voice:delete_now",
    )
    async def delete_now(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        """Delete the private voice call immediately."""

        await interaction.response.send_message(
            "Deletando a call privada agora.",
            ephemeral=True,
        )
        await self.manager.delete_call(
            channel=self.channel,
            reason=f"Call privada deletada pelo dono {interaction.user.id}",
        )

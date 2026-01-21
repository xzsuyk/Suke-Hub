import os
import discord
from discord.ext import commands, tasks

# IDs fixos de configuração
JOIN_TO_CREATE_CHANNEL_ID = 1463585275438567509
PARENT_CATEGORY_ID = 1463585275438567507
STAFF_ROLE_ID = None
FAMILY_ROLE_IDS = {1463585508918562846}

# Intents necessários para detectar eventos de voz
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Armazena IDs dos canais temporários criados
temporary_channels = set()


def get_family_role(member: discord.Member) -> discord.Role | None:
    """Retorna o cargo de família permitido, se o usuário tiver."""
    for role in member.roles:
        if role.id in FAMILY_ROLE_IDS:
            return role
    return None


@bot.event
async def on_ready() -> None:
    """Log simples quando o bot iniciar."""
    print(f"Bot conectado como {bot.user} (ID: {bot.user.id})")
    if not cleanup_empty_channels.is_running():
        cleanup_empty_channels.start()


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState | None,
    after: discord.VoiceState | None,
) -> None:
    """Cria um canal temporário quando o usuário entra no canal de criação."""
    if not after or not after.channel:
        return

    if after.channel.id != JOIN_TO_CREATE_CHANNEL_ID:
        return

    family_role = get_family_role(member)
    if not family_role:
        try:
            await member.move_to(None, reason="Sem cargo de família permitido")
        except discord.Forbidden:
            print("Permissão insuficiente para desconectar o usuário.")
        return

    guild = member.guild
    category = guild.get_channel(PARENT_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        print("Categoria de calls não encontrada ou inválida.")
        return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
        family_role: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True),
    }

    if STAFF_ROLE_ID:
        staff_role = guild.get_role(STAFF_ROLE_ID)
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True, connect=True, speak=True
            )

    channel_name = f"🔒 {family_role.name} • {member.display_name}"

    try:
        temp_channel = await guild.create_voice_channel(
            channel_name,
            category=category,
            overwrites=overwrites,
            reason="Join to Create - call temporária",
        )
    except discord.Forbidden:
        print("Permissão insuficiente para criar o canal temporário.")
        return

    temporary_channels.add(temp_channel.id)

    try:
        await member.move_to(temp_channel, reason="Mover para call temporária")
    except discord.Forbidden:
        print("Permissão insuficiente para mover o usuário.")
        try:
            await temp_channel.delete(reason="Falha ao mover usuário")
            temporary_channels.discard(temp_channel.id)
        except discord.Forbidden:
            print("Permissão insuficiente para deletar o canal criado.")


@tasks.loop(seconds=10)
async def cleanup_empty_channels() -> None:
    """Remove canais temporários vazios a cada 10 segundos."""
    to_remove = set()
    for channel_id in list(temporary_channels):
        channel = bot.get_channel(channel_id)
        if not channel:
            to_remove.add(channel_id)
            continue
        if isinstance(channel, discord.VoiceChannel) and len(channel.members) == 0:
            try:
                await channel.delete(reason="Call temporária vazia")
            except discord.Forbidden:
                print("Permissão insuficiente para deletar canal temporário.")
            to_remove.add(channel_id)

    temporary_channels.difference_update(to_remove)


def main() -> None:
    """Ponto de entrada do bot."""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN não definido no ambiente.")
    bot.run(token)


if __name__ == "__main__":
    main()

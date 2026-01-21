import os
import sqlite3
from datetime import datetime, timezone

import discord
from discord import ui
from discord.ext import commands

# CONFIG
UPLOAD_CHANNEL_ID = 1463585275438567509
FEED_CHANNEL_ID = 1463585275438567507
STAFF_ROLE_ID = None
DB_PATH = "acegram.db"
CONFIRM_UPLOAD = False

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)


def utc_now() -> str:
    """Retorna timestamp UTC em ISO."""
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    """Cria as tabelas SQLite se não existirem."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                post_id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_message_id INTEGER UNIQUE,
                guild_id INTEGER,
                author_user_id INTEGER,
                author_display_name TEXT,
                image_url TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS likes (
                feed_message_id INTEGER,
                user_id INTEGER,
                created_at TEXT,
                UNIQUE(feed_message_id, user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comments (
                comment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_message_id INTEGER,
                user_id INTEGER,
                user_display_name TEXT,
                content TEXT,
                created_at TEXT
            )
            """
        )


def insert_post(
    feed_message_id: int,
    guild_id: int,
    author_user_id: int,
    author_display_name: str,
    image_url: str,
) -> None:
    """Salva um post no banco."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO posts (
                feed_message_id,
                guild_id,
                author_user_id,
                author_display_name,
                image_url,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                feed_message_id,
                guild_id,
                author_user_id,
                author_display_name,
                image_url,
                utc_now(),
            ),
        )


def insert_like(feed_message_id: int, user_id: int) -> None:
    """Registra uma curtida."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO likes (feed_message_id, user_id, created_at)
            VALUES (?, ?, ?)
            """,
            (feed_message_id, user_id, utc_now()),
        )


def delete_like(feed_message_id: int, user_id: int) -> None:
    """Remove uma curtida."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            DELETE FROM likes
            WHERE feed_message_id = ? AND user_id = ?
            """,
            (feed_message_id, user_id),
        )


def like_exists(feed_message_id: int, user_id: int) -> bool:
    """Verifica se o usuário já curtiu."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT 1 FROM likes
            WHERE feed_message_id = ? AND user_id = ?
            """,
            (feed_message_id, user_id),
        ).fetchone()
    return row is not None


def count_likes(feed_message_id: int) -> int:
    """Conta curtidas do post."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) FROM likes WHERE feed_message_id = ?
            """,
            (feed_message_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def insert_comment(
    feed_message_id: int,
    user_id: int,
    user_display_name: str,
    content: str,
) -> None:
    """Registra comentário."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO comments (
                feed_message_id,
                user_id,
                user_display_name,
                content,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (feed_message_id, user_id, user_display_name, content, utc_now()),
        )


def delete_post_records(feed_message_id: int) -> None:
    """Remove post e seus dados associados."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM likes WHERE feed_message_id = ?", (feed_message_id,))
        conn.execute(
            "DELETE FROM comments WHERE feed_message_id = ?", (feed_message_id,)
        )
        conn.execute("DELETE FROM posts WHERE feed_message_id = ?", (feed_message_id,))


def fetch_all_post_ids() -> list[int]:
    """Busca todos os IDs de mensagens de posts."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT feed_message_id FROM posts").fetchall()
    return [int(row[0]) for row in rows]


def fetch_post_author(feed_message_id: int) -> int | None:
    """Retorna o autor do post."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT author_user_id FROM posts WHERE feed_message_id = ?",
            (feed_message_id,),
        ).fetchone()
    return int(row[0]) if row else None


def is_image_attachment(attachment: discord.Attachment) -> bool:
    """Valida se o attachment é imagem suportada."""
    if not attachment.filename:
        return False
    filename = attachment.filename.lower()
    return any(filename.endswith(ext) for ext in ALLOWED_EXTENSIONS)


def build_embed(author_display: str, author_mention: str, image_url: str) -> discord.Embed:
    """Monta o embed do post."""
    embed = discord.Embed(title=f"📸 Post de {author_display}")
    embed.set_footer(text=f"Postado por {author_mention}")
    embed.set_image(url=image_url)
    return embed


class CommentModal(ui.Modal):
    """Modal para comentário."""

    def __init__(self, feed_message_id: int):
        super().__init__(title="Comentar")
        self.feed_message_id = feed_message_id
        self.comment = ui.TextInput(
            label="Comentário",
            style=discord.TextStyle.paragraph,
            max_length=1000,
        )
        self.add_item(self.comment)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        content = self.comment.value.strip()
        if not content:
            await interaction.response.send_message(
                "Comentário vazio não é permitido.", ephemeral=True
            )
            return

        insert_comment(
            self.feed_message_id,
            interaction.user.id,
            interaction.user.display_name,
            content,
        )

        feed_channel = interaction.client.get_channel(FEED_CHANNEL_ID)
        if isinstance(feed_channel, discord.TextChannel):
            try:
                post_message = await feed_channel.fetch_message(self.feed_message_id)
                await post_message.reply(
                    f"💬 {interaction.user.mention}: {content}"
                )
            except discord.NotFound:
                pass

        print(f"Comentário registrado no post {self.feed_message_id}.")
        await interaction.response.send_message("Comentário enviado!", ephemeral=True)


class AcegramView(ui.View):
    """View persistente com botões do post."""

    def __init__(self, feed_message_id: int, author_user_id: int, like_count: int):
        super().__init__(timeout=None)
        self.feed_message_id = feed_message_id
        self.author_user_id = author_user_id

        like_button = ui.Button(
            label=f"❤️ Curtir ({like_count})",
            custom_id=f"acegram_like:{feed_message_id}",
        )
        like_button.callback = self.handle_like

        comment_button = ui.Button(
            label="💬 Comentar",
            custom_id=f"acegram_comment:{feed_message_id}",
        )
        comment_button.callback = self.handle_comment

        delete_button = ui.Button(
            label="🗑️ Deletar",
            style=discord.ButtonStyle.danger,
            custom_id=f"acegram_delete:{feed_message_id}",
        )
        delete_button.callback = self.handle_delete

        self.add_item(like_button)
        self.add_item(comment_button)
        self.add_item(delete_button)

    async def handle_like(self, interaction: discord.Interaction) -> None:
        """Alterna curtida do usuário."""
        if like_exists(self.feed_message_id, interaction.user.id):
            delete_like(self.feed_message_id, interaction.user.id)
            print(
                f"Curtida removida por {interaction.user.id} no post {self.feed_message_id}."
            )
        else:
            insert_like(self.feed_message_id, interaction.user.id)
            print(
                f"Curtida adicionada por {interaction.user.id} no post {self.feed_message_id}."
            )

        new_count = count_likes(self.feed_message_id)
        for item in self.children:
            if isinstance(item, ui.Button) and item.custom_id == f"acegram_like:{self.feed_message_id}":
                item.label = f"❤️ Curtir ({new_count})"

        await interaction.response.edit_message(view=self)

    async def handle_comment(self, interaction: discord.Interaction) -> None:
        """Abre o modal de comentário."""
        await interaction.response.send_modal(CommentModal(self.feed_message_id))

    async def handle_delete(self, interaction: discord.Interaction) -> None:
        """Deleta o post se autorizado."""
        allowed = interaction.user.id == self.author_user_id
        if not allowed and STAFF_ROLE_ID:
            if isinstance(interaction.user, discord.Member):
                allowed = any(role.id == STAFF_ROLE_ID for role in interaction.user.roles)

        if not allowed:
            await interaction.response.send_message(
                "Você não pode deletar este post.", ephemeral=True
            )
            return

        try:
            await interaction.message.delete()
        except discord.Forbidden:
            await interaction.response.send_message(
                "Não tenho permissão para deletar este post.", ephemeral=True
            )
            return

        delete_post_records(self.feed_message_id)
        print(f"Post {self.feed_message_id} deletado.")
        await interaction.response.send_message("Post deletado.", ephemeral=True)


@bot.event
async def on_ready() -> None:
    """Inicializa o banco e registra views persistentes."""
    init_db()
    for feed_message_id in fetch_all_post_ids():
        author_id = fetch_post_author(feed_message_id)
        if author_id is None:
            continue
        like_count = count_likes(feed_message_id)
        bot.add_view(AcegramView(feed_message_id, author_id, like_count))

    print(f"Acegram conectado como {bot.user} (ID: {bot.user.id})")


@bot.event
async def on_message(message: discord.Message) -> None:
    """Processa uploads de imagens no canal configurado."""
    if message.author.bot:
        return

    if not message.guild or message.channel.id != UPLOAD_CHANNEL_ID:
        return

    attachment = next(
        (att for att in message.attachments if is_image_attachment(att)), None
    )
    if not attachment:
        return

    feed_channel = message.guild.get_channel(FEED_CHANNEL_ID)
    if not isinstance(feed_channel, discord.TextChannel):
        return

    embed = build_embed(message.author.display_name, message.author.mention, attachment.url)
    try:
        feed_message = await feed_channel.send(embed=embed)
    except discord.Forbidden:
        print("Permissão insuficiente para postar no feed.")
        return

    view = AcegramView(feed_message.id, message.author.id, 0)
    await feed_message.edit(view=view)

    insert_post(
        feed_message.id,
        message.guild.id,
        message.author.id,
        message.author.display_name,
        attachment.url,
    )

    print(f"Post publicado no feed: {feed_message.id}")
    if CONFIRM_UPLOAD:
        await message.channel.send(
            "✅ Foto publicada no feed!", reference=message, mention_author=False
        )

    await bot.process_commands(message)


def main() -> None:
    """Ponto de entrada do bot."""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN não definido no ambiente.")
    bot.run(token)


if __name__ == "__main__":
    main()

# ---
# GUIA RÁPIDO
# 1) Instalar dependência: pip install -U discord.py
# 2) Definir DISCORD_TOKEN:
#    - Windows PowerShell: setx DISCORD_TOKEN "TOKEN" (reabra o terminal)
#    - Linux/macOS: export DISCORD_TOKEN="TOKEN"
# 3) Rodar: python bot.py
#
# COMO CONFIGURAR OS CANAIS
# - Crie um canal de texto para upload e outro para feed.
# - Ative Modo Desenvolvedor no Discord e copie os IDs dos canais.
#
# PERMISSÕES MÍNIMAS DO BOT
# - View Channels, Send Messages, Embed Links, Attach Files,
#   Read Message History. Manage Messages é opcional (para deletar uploads).
# - Use Application Commands só se usar slash (não necessário aqui).
# - Não precisa habilitar Server Members Intent para este bot.

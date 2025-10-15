from keep_alive import keep_alive
keep_alive()
import os
TOKEN = os.getenv("DISCORD_TOKEN")
import os
import sqlite3
import asyncio
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands, tasks

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.members = True
INTENTS.guilds = True
INTENTS.invites = True
INTENTS.voice_states = True

BOT_PREFIX = "!"  # non utilisé pour les commandes; slash commands via app_commands
TOKEN = os.getenv("DISCORD_TOKEN")

DB_PATH = "data.db"

class EconomyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=BOT_PREFIX, intents=INTENTS)
        self.synced = False
        self.invite_cache = {}  # guild_id -> {code: uses}
        self.voice_sessions = {}  # (guild_id, user_id) -> start_timestamp

    async def setup_hook(self):
        init_db()
        # Pré-charger les invites
        for guild in self.guilds:
            await self.refresh_invite_cache(guild)
        # Tâche: comptage minute vocale
        voice_tick.start()

    async def on_ready(self):
        if not self.synced:
            await tree.sync()
            self.synced = True
        print(f"Logged in as {self.user} (ID: {self.user.id})")

    async def refresh_invite_cache(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {inv.code: inv.uses or 0 for inv in invites}
        except discord.Forbidden:
            # Le bot n’a pas la permission de voir les invites
            self.invite_cache[guild.id] = {}

bot = EconomyBot()
tree = app_commands.CommandTree(bot)

# -------------- Database --------------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        guild_id INTEGER,
        user_id INTEGER,
        balance INTEGER DEFAULT 0,
        msg_count INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, user_id)
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS config (
        guild_id INTEGER PRIMARY KEY,
        msg_threshold INTEGER DEFAULT 10,
        msg_reward INTEGER DEFAULT 5,
        voice_reward_per_min INTEGER DEFAULT 2,
        invite_reward INTEGER DEFAULT 100,
        logs_channel_id INTEGER
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS shop (
        guild_id INTEGER,
        name TEXT,
        price INTEGER,
        description TEXT,
        PRIMARY KEY (guild_id, name)
    )""")
    conn.commit()
    conn.close()

def db_execute(query, params=(), fetchone=False, fetchall=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(query, params)
    result = None
    if fetchone:
        result = c.fetchone()
    elif fetchall:
        result = c.fetchall()
    conn.commit()
    conn.close()
    return result

def ensure_user(guild_id: int, user_id: int):
    db_execute("""
        INSERT OR IGNORE INTO users (guild_id, user_id, balance, msg_count)
        VALUES (?, ?, 0, 0)
    """, (guild_id, user_id))

def get_config(guild_id: int):
    row = db_execute("SELECT * FROM config WHERE guild_id = ?", (guild_id,), fetchone=True)
    if not row:
        db_execute("""
            INSERT INTO config (guild_id, msg_threshold, msg_reward, voice_reward_per_min, invite_reward, logs_channel_id)
            VALUES (?, 10, 5, 2, 100, NULL)
        """, (guild_id,))
        return get_config(guild_id)
    return row

def add_balance(guild_id: int, user_id: int, amount: int):
    ensure_user(guild_id, user_id)
    db_execute("UPDATE users SET balance = balance + ? WHERE guild_id = ? AND user_id = ?", (amount, guild_id, user_id))

def set_msg_count(guild_id: int, user_id: int, count: int):
    ensure_user(guild_id, user_id)
    db_execute("UPDATE users SET msg_count = ? WHERE guild_id = ? AND user_id = ?", (count, guild_id, user_id))

def get_user(guild_id: int, user_id: int):
    ensure_user(guild_id, user_id)
    return db_execute("SELECT * FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id), fetchone=True)

def get_logs_channel(guild_id: int):
    cfg = get_config(guild_id)
    return cfg["logs_channel_id"]

async def send_log(guild: discord.Guild, content: str):
    channel_id = get_logs_channel(guild.id)
    if channel_id:
        channel = guild.get_channel(channel_id)
        if channel:
            await channel.send(content)

# -------------- Events --------------

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    # Compteur de messages -> récompense
    ensure_user(message.guild.id, message.author.id)
    user = get_user(message.guild.id, message.author.id)
    cfg = get_config(message.guild.id)
    new_count = (user["msg_count"] + 1)
    threshold = cfg["msg_threshold"]
    reward = cfg["msg_reward"]

    if threshold > 0 and new_count >= threshold:
        add_balance(message.guild.id, message.author.id, reward)
        set_msg_count(message.guild.id, message.author.id, 0)
        # Feedback léger
        try:
            await message.add_reaction("💸")
        except discord.HTTPException:
            pass
    else:
        set_msg_count(message.guild.id, message.author.id, new_count)

    await bot.process_commands(message)  # pour compat si tu ajoutes des commandes textuelles

@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    # Comparer invites
    try:
        current_invites = await guild.invites()
    except discord.Forbidden:
        current_invites = []
    old_map = bot.invite_cache.get(guild.id, {})
    inviter = None
    for inv in current_invites:
        old_uses = old_map.get(inv.code, 0)
        if (inv.uses or 0) > old_uses:
            inviter = inv.inviter
            break
    await bot.refresh_invite_cache(guild)

    if inviter and inviter.id != member.id:
        cfg = get_config(guild.id)
        reward = cfg["invite_reward"]
        add_balance(guild.id, inviter.id, reward)
        await send_log(guild, f"📣 Invitation: {inviter.mention} a gagné {reward} pour avoir invité {member.mention}.")

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    key = (member.guild.id, member.id)
    # Début de session
    if (after.channel is not None) and (before.channel is None):
        bot.voice_sessions[key] = datetime.utcnow().timestamp()
    # Fin de session
    if (before.channel is not None) and (after.channel is None):
        start = bot.voice_sessions.pop(key, None)
        if start:
            await credit_voice_time(member.guild, member, start)

@tasks.loop(seconds=60)
async def voice_tick():
    # Crédite chaque minute passée en vocal (session en cours)
    now = datetime.utcnow().timestamp()
    for (guild_id, user_id), start in list(bot.voice_sessions.items()):
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        member = guild.get_member(user_id)
        if not member:
            continue
        # On crédite par minute écoulée
        await credit_voice_time(guild, member, start, tick=True)
        # Reset start time à now pour compter par tranche
        bot.voice_sessions[(guild_id, user_id)] = now

async def credit_voice_time(guild: discord.Guild, member: discord.Member, start_ts: float, tick: bool=False):
    cfg = get_config(guild.id)
    per_min = cfg["voice_reward_per_min"]
    if per_min <= 0:
        return
    elapsed_seconds = max(0, int(datetime.utcnow().timestamp() - start_ts))
    minutes = elapsed_seconds // 60
    if minutes <= 0 and tick:
        minutes = 1  # au moins 1/min pour le tick pour rendre la boucle utile
    if minutes > 0:
        add_balance(guild.id, member.id, per_min * minutes)
        # Feedback léger dans logs seulement si fin de session
        if not tick:
            await send_log(guild, f"🎧 Vocal: {member.mention} a gagné {per_min * minutes} pour {minutes} minute(s) en vocal.")

# -------------- Slash Commands --------------

@tree.command(name="balance", description="Voir ton solde.")
async def balance(interaction: discord.Interaction):
    user = get_user(interaction.guild.id, interaction.user.id)
    await interaction.response.send_message(f"💰 Solde de {interaction.user.mention}: {user['balance']}")

@tree.command(name="shop", description="Afficher la boutique.")
async def shop(interaction: discord.Interaction):
    items = db_execute("SELECT name, price, description FROM shop WHERE guild_id = ? ORDER BY price ASC", (interaction.guild.id,), fetchall=True)
    if not items:
        await interaction.response.send_message("🛍️ La boutique est vide.")
        return
    embed = discord.Embed(title="Boutique", color=0x00B2FF)
    for row in items:
        name = row["name"]
        price = row["price"]
        desc = row["description"] or ""
        embed.add_field(name=f"{name} — {price}", value=desc if desc else " ", inline=False)
    await interaction.response.send_message(embed=embed)

@tree.command(name="buy", description="Acheter un objet de la boutique (par nom).")
@app_commands.describe(item="Nom exact de l'objet à acheter")
async def buy(interaction: discord.Interaction, item: str):
    row = db_execute("SELECT price FROM shop WHERE guild_id = ? AND name = ?", (interaction.guild.id, item), fetchone=True)
    if not row:
        await interaction.response.send_message(f"❌ L'objet '{item}' n'existe pas.", ephemeral=True)
        return
    price = row["price"]
    user = get_user(interaction.guild.id, interaction.user.id)
    if user["balance"] < price:
        await interaction.response.send_message(f"⛔ Solde insuffisant. Prix: {price}, Solde: {user['balance']}.", ephemeral=True)
        return
    add_balance(interaction.guild.id, interaction.user.id, -price)
    await interaction.response.send_message(f"✅ Achat réussi: {item} pour {price}.")
    await send_log(interaction.guild, f"🧾 Achat: {interaction.user.mention} a acheté '{item}' pour {price}.")

# ---- Admin-only helpers ----
def is_admin(member: discord.Member):
    return member.guild_permissions.administrator

async def require_admin(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Cette commande est réservée aux administrateurs.", ephemeral=True)
        return False
    return True

@tree.command(name="shop_add", description="Ajouter un objet à la boutique (admin).")
@app_commands.describe(name="Nom de l'objet", price="Prix", description="Description (optionnel)")
async def shop_add(interaction: discord.Interaction, name: str, price: app_commands.Range[int, 1, 10_000_000], description: str=None):
    if not await require_admin(interaction):
        return
    db_execute("""
        INSERT OR REPLACE INTO shop (guild_id, name, price, description)
        VALUES (?, ?, ?, ?)
    """, (interaction.guild.id, name, price, description))
    await interaction.response.send_message(f"🛒 Objet ajouté: {name} — {price}.")

@tree.command(name="shop_remove", description="Retirer un objet de la boutique (admin).")
@app_commands.describe(name="Nom de l'objet")
async def shop_remove(interaction: discord.Interaction, name: str):
    if not await require_admin(interaction):
        return
    db_execute("DELETE FROM shop WHERE guild_id = ? AND name = ?", (interaction.guild.id, name))
    await interaction.response.send_message(f"🗑️ Objet retiré: {name}.")

@tree.command(name="shop_setprice", description="Modifier le prix d'un objet (admin).")
@app_commands.describe(name="Nom de l'objet", price="Nouveau prix")
async def shop_setprice(interaction: discord.Interaction, name: str, price: app_commands.Range[int, 1, 10_000_000]):
    if not await require_admin(interaction):
        return
    exists = db_execute("SELECT 1 FROM shop WHERE guild_id = ? AND name = ?", (interaction.guild.id, name), fetchone=True)
    if not exists:
        await interaction.response.send_message(f"❌ L'objet '{name}' n'existe pas.", ephemeral=True)
        return
    db_execute("UPDATE shop SET price = ? WHERE guild_id = ? AND name = ?", (price, interaction.guild.id, name))
    await interaction.response.send_message(f"✏️ Prix mis à jour: {name} — {price}.")

@tree.command(name="config_message", description="Configurer les gains par messages (admin).")
@app_commands.describe(threshold="Nombre de messages pour déclencher le gain", reward="Gain attribué quand le seuil est atteint")
async def config_message(interaction: discord.Interaction, threshold: app_commands.Range[int, 1, 10_000], reward: app_commands.Range[int, 0, 10_000_000]):
    if not await require_admin(interaction):
        return
    db_execute("UPDATE config SET msg_threshold = ?, msg_reward = ? WHERE guild_id = ?", (threshold, reward, interaction.guild.id))
    await interaction.response.send_message(f"📨 Config messages: seuil={threshold}, gain={reward}.")

@tree.command(name="config_voice", description="Configurer les gains par minute en vocal (admin).")
@app_commands.describe(reward_per_min="Gain par minute en salon vocal")
async def config_voice(interaction: discord.Interaction, reward_per_min: app_commands.Range[int, 0, 10_000_000]):
    if not await require_admin(interaction):
        return
    db_execute("UPDATE config SET voice_reward_per_min = ? WHERE guild_id = ?", (reward_per_min, interaction.guild.id))
    await interaction.response.send_message(f"🎧 Config vocal: {reward_per_min} par minute.")

@tree.command(name="config_invite", description="Configurer les gains pour invitations (admin).")
@app_commands.describe(reward="Gain attribué à l'invitant quand un nouveau membre rejoint")
async def config_invite(interaction: discord.Interaction, reward: app_commands.Range[int, 0, 10_000_000]):
    if not await require_admin(interaction):
        return
    db_execute("UPDATE config SET invite_reward = ? WHERE guild_id = ?", (reward, interaction.guild.id))
    await interaction.response.send_message(f"📣 Config invitation: {reward} par membre invité.")

@tree.command(name="logs_set", description="Définir le salon pour les logs (admin).")
@app_commands.describe(channel="Salon de logs")
async def logs_set(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await require_admin(interaction):
        return
    exists = db_execute("SELECT 1 FROM config WHERE guild_id = ?", (interaction.guild.id,), fetchone=True)
    if not exists:
        get_config(interaction.guild.id)  # crée par défaut
    db_execute("UPDATE config SET logs_channel_id = ? WHERE guild_id = ?", (channel.id, interaction.guild.id))
    await interaction.response.send_message(f"🪵 Salon de logs défini: {channel.mention}")

# -------------- Run --------------
if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: set DISCORD_TOKEN env var.")
    else:
        bot.run(TOKEN)

from dotenv import load_dotenv
load_dotenv()
import discord
import asyncio
import json
from discord.ext import commands, tasks

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# Chargement des données
def load_data():
    try:
        with open("data.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        # Création du fichier si absent
        default_data = {
            "users": {},
            "shop": {
                "VIP": 50000,
                "PubYT": 150000
            },
            "log_channel": None,
            "shop_color": "#00FFAA",
            "message_threshold": 10,
            "message_reward": 100,
            "voice_interval": 600,
            "voice_reward": 200
        }
        with open("data.json", "w") as f:
            json.dump(default_data, f, indent=4)
        return default_data

def save_data(data):
    with open("data.json", "w") as f:
        json.dump(data, f, indent=4)

data = load_data()

# Fonction de log
async def log_action(bot, message):
    if data["log_channel"]:
        channel = bot.get_channel(data["log_channel"])
        if channel:
            await channel.send(message)

@tasks.loop(seconds=60)
async def voice_loop():
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if member.bot:
                    continue
                user_id = str(member.id)
                user = data["users"].setdefault(user_id, {"coins": 0, "messages": 0, "daily_gain": 0})
                if user["daily_gain"] + data["voice_reward"] <= 20000:
                    user["coins"] += data["voice_reward"]
                    user["daily_gain"] += data["voice_reward"]
                    await log_action(bot, f"🔊 {member.name} a gagné {data['voice_reward']} coins en vocal.")
    save_data(data)

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user}")
    voice_loop.start()

@bot.command()
async def balance(ctx):
    user_id = str(ctx.author.id)
    coins = data["users"].get(user_id, {}).get("coins", 0)
    await ctx.send(f"💰 Tu as {coins} coins.")

@bot.command()
async def give(ctx, member: discord.Member, amount: int):
    giver_id = str(ctx.author.id)
    receiver_id = str(member.id)
    giver = data["users"].setdefault(giver_id, {"coins": 0, "messages": 0, "daily_gain": 0})
    receiver = data["users"].setdefault(receiver_id, {"coins": 0, "messages": 0, "daily_gain": 0})

    if amount <= 0 or giver["coins"] < amount:
        await ctx.send("❌ Montant invalide ou solde insuffisant.")
        return
    if giver["daily_gain"] + amount > 20000:
        await ctx.send("🚫 Tu as atteint ta limite journalière.")
        return

    giver["coins"] -= amount
    giver["daily_gain"] += amount
    receiver["coins"] += amount
    save_data(data)
    await log_action(bot, f"🎁 {ctx.author.name} → {member.name} : {amount} coins")
    await ctx.send(f"🎁 {ctx.author.name} a donné {amount} coins à {member.name}.")

@bot.command()
async def shop(ctx):
    embed = discord.Embed(title="🛍️ Boutique", color=int(data["shop_color"].replace("#", ""), 16))
    for item, price in data["shop"].items():
        embed.add_field(name=item, value=f"{price} coins", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def buy(ctx, item: str):
    user_id = str(ctx.author.id)
    user = data["users"].setdefault(user_id, {"coins": 0, "messages": 0, "daily_gain": 0})

    item = item.capitalize()
    if item not in data["shop"]:
        await ctx.send("❌ Cet objet n'existe pas.")
        return

    price = data["shop"][item]
    if user["coins"] < price:
        await ctx.send("💸 Tu n'as pas assez de coins.")
        return

    user["coins"] -= price
    save_data(data)

    await log_action(bot, f"🛍️ {ctx.author.name} a acheté '{item}' pour {price} coins.")

    if item == "VIP":
        role = discord.utils.get(ctx.guild.roles, name="VIP")
        if role:
            await ctx.author.add_roles(role)
            await ctx.send("🎖️ Rôle VIP attribué !")
        else:
            await ctx.send("⚠️ Le rôle VIP n'existe pas sur ce serveur.")
    elif item == "Pubyt":
        await ctx.send("📢 Tu as acheté une pub YouTube ! Contacte un admin pour la publier.")

@bot.command()
async def shopadd(ctx, item: str, price: int):
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("🚫 Tu n'as pas la permission d'ajouter des objets.")
        return

    item = item.capitalize()
    data["shop"][item] = price
    save_data(data)
    await log_action(bot, f"➕ {ctx.author.name} a ajouté '{item}' à la boutique pour {price} coins.")
    await ctx.send(f"✅ Objet '{item}' ajouté à la boutique pour {price} coins.")

@bot.command()
async def addmoney(ctx, member: discord.Member, amount: int):
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("🚫 Tu n'as pas la permission d'utiliser cette commande.")
        return

    if amount <= 0:
        await ctx.send("❌ Le montant doit être positif.")
        return

    user_id = str(member.id)
    user = data["users"].setdefault(user_id, {"coins": 0, "messages": 0, "daily_gain": 0})
    user["coins"] += amount
    save_data(data)

    await log_action(bot, f"💸 {ctx.author.name} a ajouté {amount} coins à {member.name}.")
    await ctx.send(f"✅ {member.name} a reçu {amount} coins.")

@bot.command()
async def removemoney(ctx, member: discord.Member, amount: int):
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("🚫 Tu n'as pas la permission d'utiliser cette commande.")
        return

    if amount <= 0:
        await ctx.send("❌ Le montant doit être positif.")
        return

    user_id = str(member.id)
    user = data["users"].setdefault(user_id, {"coins": 0, "messages": 0, "daily_gain": 0})

    if user["coins"] < amount:
        await ctx.send("💸 Le joueur n'a pas assez de coins.")
        return

    user["coins"] -= amount
    save_data(data)

    await log_action(bot, f"❌ {ctx.author.name} a retiré {amount} coins à {member.name}.")
    await ctx.send(f"✅ {amount} coins retirés à {member.name}.")

@bot.command()
async def setlog(ctx, channel: discord.TextChannel):
    if ctx.author.guild_permissions.administrator:
        data["log_channel"] = channel.id
        save_data(data)
        await ctx.send(f"📜 Salon de logs défini : {channel.mention}")

@bot.command()
async def setcolor(ctx, hex_code: str):
    if ctx.author.guild_permissions.administrator:
        data["shop_color"] = hex_code
        save_data(data)
        await ctx.send(f"🎨 Couleur de la boutique changée en {hex_code}")

@bot.command()
async def setthreshold(ctx, messages: int, reward: int):
    if ctx.author.guild_permissions.administrator:
        data["message_threshold"] = messages
        data["message_reward"] = reward
        save_data(data)
        await ctx.send(f"💬 Gain configuré : {reward} coins tous les {messages} messages.")

@bot.command()
async def setvoicegain(ctx, interval: int, reward: int):
    if ctx.author.guild_permissions.administrator:
        data["voice_interval"] = interval
        data["voice_reward"] = reward
        voice_loop.change_interval(seconds=interval)
        save_data(data)
        await ctx.send(f"🔊 Gain vocal configuré : {reward} coins toutes les {interval} secondes.")

@bot.command()
async def resetdaily(ctx):
    if ctx.author.guild_permissions.administrator:
        for user in data["users"].values():
            user["daily_gain"] = 0
        save_data(data)
        await ctx.send("🔄 Limites journalières réinitialisées.")

# 🚀 Lancement du bot
import os
bot.run(os.getenv("DISCORD_TOKEN"))
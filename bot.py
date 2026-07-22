import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
import time
import database as db

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN environment variable not set.")

# ── Bot Setup ─────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

class DokkaebiBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        # invite_cache[guild_id] = {code: uses}
        self.invite_cache: dict[int, dict[str, int]] = {}
        # generate cooldowns: {(guild_id, user_id): timestamp}
        self.gen_cooldowns: dict[tuple, float] = {}
        # drop tasks per guild
        self.drop_tasks: dict[int, asyncio.Task] = {}

    async def setup_hook(self):
        await db.setup_db()
        await self.tree.sync()
        print("Slash commands synced.")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching, name="DOKKAEBI 💎"
        ))
        for guild in self.guilds:
            await self._cache_invites(guild)

    async def _cache_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
            for inv in invites:
                if inv.inviter:
                    await db.upsert_invite(str(guild.id), inv.code, str(inv.inviter.id), inv.uses)
        except discord.Forbidden:
            pass

    async def on_guild_join(self, guild: discord.Guild):
        await self._cache_invites(guild)

    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild:
            self.invite_cache.setdefault(invite.guild.id, {})[invite.code] = 0

    async def on_invite_delete(self, invite: discord.Invite):
        if invite.guild:
            self.invite_cache.get(invite.guild.id, {}).pop(invite.code, None)

    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        try:
            new_invites = await guild.invites()
        except discord.Forbidden:
            return
        old_cache = self.invite_cache.get(guild.id, {})
        used_invite = None
        for inv in new_invites:
            old_uses = old_cache.get(inv.code, 0)
            if inv.uses > old_uses and inv.inviter:
                used_invite = inv
                break
        self.invite_cache[guild.id] = {i.code: i.uses for i in new_invites}
        if used_invite and used_invite.inviter:
            await db.upsert_invite(
                str(guild.id), used_invite.code,
                str(used_invite.inviter.id), used_invite.uses
            )

    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        await db.increment_message_count(str(message.guild.id), str(message.author.id))
        await self.process_commands(message)


bot = DokkaebiBot()

# ── Helpers ───────────────────────────────────────────────────────────────────

RED   = 0xE74C3C
BLUE  = 0x3498DB
GREEN = 0x2ECC71
GOLD  = 0xF1C40F
DARK  = 0x2C2F33

def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message(
            embed=discord.Embed(description="❌ You need **Administrator** permission.", color=RED),
            ephemeral=True
        )
        return False
    return app_commands.check(predicate)


# ── /generate ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="generate", description="Generate an account from stock.")
@app_commands.describe(category="The category to generate from (Free or Premium)")
@app_commands.choices(category=[
    app_commands.Choice(name="Free",    value="Free"),
    app_commands.Choice(name="Premium", value="Premium"),
])
async def generate(interaction: discord.Interaction, category: app_commands.Choice[str]):
    guild_id = str(interaction.guild_id)
    user_id  = str(interaction.user.id)
    cat      = category.value
    member   = interaction.user  # is a Member in guilds

    # ── Role check ────────────────────────────────────────────────────────────
    role_key = "free_role" if cat == "Free" else "premium_role"
    required_role_id = await db.get_config(guild_id, role_key)
    if required_role_id:
        member_role_ids = [str(r.id) for r in member.roles]
        if required_role_id not in member_role_ids:
            role_mention = f"<@&{required_role_id}>"
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"{'🆓' if cat == 'Free' else '💎'} You need the {role_mention} role to generate **{cat}** accounts.",
                    color=RED
                ),
                ephemeral=True
            )
            return
    else:
        # No role set — fall back to subscription gate for Premium
        if cat == "Premium":
            tier = await db.get_subscription(guild_id, user_id)
            if tier != "Premium":
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description="💎 You need a **Premium** subscription to generate from this category.",
                        color=RED
                    ),
                    ephemeral=True
                )
                return

    # ── Cooldown check ────────────────────────────────────────────────────────
    cooldown_str = await db.get_config(guild_id, "gen_cooldown")
    cooldown = int(cooldown_str) if cooldown_str else 0
    key = (interaction.guild_id, interaction.user.id)
    if cooldown > 0:
        last = bot.gen_cooldowns.get(key, 0)
        remaining = cooldown - (time.time() - last)
        if remaining > 0:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"⏳ You're on cooldown! Try again in **{remaining:.1f}s**.",
                    color=RED
                ),
                ephemeral=True
            )
            return

    # ── Thinking message ──────────────────────────────────────────────────────
    await interaction.response.send_message(
        embed=discord.Embed(description="⚙️ Generator is thinking...", color=DARK)
    )

    account = await db.pop_stock(guild_id, cat)
    if not account:
        await interaction.edit_original_response(
            embed=discord.Embed(
                title="📦 Out of Stock",
                description=f"There are no **{cat}** accounts available right now.",
                color=RED
            )
        )
        return

    bot.gen_cooldowns[key] = time.time()

    # ── Build result embed ────────────────────────────────────────────────────
    embed = discord.Embed(
        title="🔫 Account Generated",
        description=f"{interaction.user.mention} generated an account!",
        color=GREEN
    )
    embed.add_field(name="Category", value=f"{'🆓 Free' if cat == 'Free' else '💎 Premium'}", inline=True)
    embed.add_field(name="Account", value=f"```{account}```", inline=False)
    embed.set_footer(text="DOKKAEBI 💎")

    # Attach banner image if one has been set
    image_url = await db.get_config(guild_id, "gen_image_url")
    if image_url:
        embed.set_image(url=image_url)

    await interaction.edit_original_response(embed=embed)

    # ── Log to gen log channel ────────────────────────────────────────────────
    log_ch_id = await db.get_config(guild_id, "gen_log_channel")
    if log_ch_id:
        ch = interaction.guild.get_channel(int(log_ch_id))
        if ch:
            log_embed = discord.Embed(
                title="🔫 Account Generated",
                description=f"{interaction.user.mention} generated a **{cat}** account.",
                color=BLUE
            )
            log_embed.add_field(name="Account", value=f"```{account}```", inline=False)
            if image_url:
                log_embed.set_thumbnail(url=image_url)
            log_embed.set_footer(text="DOKKAEBI 💎")
            await ch.send(embed=log_embed)


# ── /setbotimage ──────────────────────────────────────────────────────────────

@bot.tree.command(name="setbotimage", description="Set the banner image shown on generated accounts. Upload from your camera roll. (Admin)")
@app_commands.describe(image="Upload an image from your camera roll or files")
@is_admin()
async def setbotimage(interaction: discord.Interaction, image: discord.Attachment):
    if not image.content_type or not image.content_type.startswith("image/"):
        await interaction.response.send_message(
            embed=discord.Embed(description="❌ Please upload a valid image file (PNG, JPG, GIF, etc.).", color=RED),
            ephemeral=True
        )
        return

    await db.set_config(str(interaction.guild_id), "gen_image_url", image.url)

    embed = discord.Embed(
        title="🖼️ Bot Image Set",
        description="This image will now appear on every generated account embed.",
        color=GREEN
    )
    embed.set_image(url=image.url)
    embed.set_footer(text="DOKKAEBI 💎")
    await interaction.response.send_message(embed=embed)


# ── /setrole ──────────────────────────────────────────────────────────────────

@bot.tree.command(name="setrole", description="Set which role can use Free or Premium generate. (Admin)")
@app_commands.describe(
    category="Which generate category to gate",
    role="The role required to use this category (leave empty to remove the requirement)"
)
@app_commands.choices(category=[
    app_commands.Choice(name="Free",    value="Free"),
    app_commands.Choice(name="Premium", value="Premium"),
])
@is_admin()
async def setrole(
    interaction: discord.Interaction,
    category: app_commands.Choice[str],
    role: discord.Role | None = None
):
    guild_id = str(interaction.guild_id)
    role_key = "free_role" if category.value == "Free" else "premium_role"

    if role is None:
        # Remove the requirement
        await db.set_config(guild_id, role_key, "")
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔓 Role Requirement Removed",
                description=f"**{category.value}** generate is now open to everyone (default rules apply).",
                color=GREEN
            )
        )
    else:
        await db.set_config(guild_id, role_key, str(role.id))
        emoji = "🆓" if category.value == "Free" else "💎"
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔒 Role Set",
                description=f"{emoji} Only members with {role.mention} can now use **{category.value}** generate.",
                color=GREEN
            )
        )


# ── /viewstock ────────────────────────────────────────────────────────────────

@bot.tree.command(name="viewstock", description="View current stock counts.")
async def viewstock(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    counts   = await db.get_all_stock_counts(guild_id)

    free    = counts.get("Free", 0)
    premium = counts.get("Premium", 0)

    embed = discord.Embed(title="📦 Stock Status", color=BLUE)
    embed.add_field(name="🆓 Free",    value=str(free),    inline=False)
    embed.add_field(name="💎 Premium", value=str(premium), inline=False)
    embed.set_footer(text="DOKKAEBI 💎")
    await interaction.response.send_message(embed=embed)


# ── /addstock ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="addstock", description="Add accounts to stock. (Admin)")
@app_commands.describe(
    category="Free or Premium",
    file="Text file containing accounts, one per line"
)
@app_commands.choices(category=[
    app_commands.Choice(name="Free",    value="Free"),
    app_commands.Choice(name="Premium", value="Premium"),
])
@is_admin()
async def addstock(interaction: discord.Interaction, category: app_commands.Choice[str], file: discord.Attachment):
    guild_id = str(interaction.guild_id)

    content_type = (file.content_type or "").lower()
    filename = (file.filename or "").lower()
    is_text_file = content_type.startswith("text/") or filename.endswith((".txt", ".csv"))
    if not is_text_file:
        await interaction.response.send_message(
            embed=discord.Embed(description="❌ Please upload a valid text file (.txt, .csv, etc.).", color=RED),
            ephemeral=True
        )
        return

    try:
        raw_bytes = await file.read()
        accounts = raw_bytes.decode("utf-8")
    except Exception:
        await interaction.response.send_message(
            embed=discord.Embed(description="❌ Please upload a valid text file (.txt, .csv, etc.).", color=RED),
            ephemeral=True
        )
        return

    lines = [l.strip() for l in accounts.strip().splitlines() if l.strip()]
    if not lines:
        await interaction.response.send_message(
            embed=discord.Embed(description="❌ No valid accounts provided.", color=RED), ephemeral=True
        )
        return
    await db.add_stock(guild_id, category.value, lines)
    await interaction.response.send_message(
        embed=discord.Embed(
            title="✅ Stock Added",
            description=f"Added **{len(lines)}** accounts to **{category.value}** stock.",
            color=GREEN
        )
    )


# ── /clearstock ───────────────────────────────────────────────────────────────

@bot.tree.command(name="clearstock", description="Clear all stock in a category. (Admin)")
@app_commands.describe(category="Free or Premium")
@app_commands.choices(category=[
    app_commands.Choice(name="Free",    value="Free"),
    app_commands.Choice(name="Premium", value="Premium"),
])
@is_admin()
async def clearstock(interaction: discord.Interaction, category: app_commands.Choice[str]):
    await db.clear_stock(str(interaction.guild_id), category.value)
    await interaction.response.send_message(
        embed=discord.Embed(
            title="🗑️ Stock Cleared",
            description=f"All **{category.value}** stock has been cleared.",
            color=RED
        )
    )


# ── /edit ─────────────────────────────────────────────────────────────────────

@bot.tree.command(name="edit", description="Edit a stock item by its position. (Admin)")
@app_commands.describe(
    category="Free or Premium",
    line_number="Line number (1-based) to edit",
    new_content="New account string"
)
@app_commands.choices(category=[
    app_commands.Choice(name="Free",    value="Free"),
    app_commands.Choice(name="Premium", value="Premium"),
])
@is_admin()
async def edit_cmd(
    interaction: discord.Interaction,
    category: app_commands.Choice[str],
    line_number: int,
    new_content: str
):
    guild_id = str(interaction.guild_id)
    items = await db.get_stock_list(guild_id, category.value)
    idx = line_number - 1
    if idx < 0 or idx >= len(items):
        await interaction.response.send_message(
            embed=discord.Embed(description=f"❌ Line {line_number} not found. Stock has {len(items)} item(s).", color=RED),
            ephemeral=True
        )
        return
    item_id = items[idx][0]
    await db.edit_stock_item(item_id, new_content)
    await interaction.response.send_message(
        embed=discord.Embed(
            title="✏️ Stock Edited",
            description=f"Line **{line_number}** of **{category.value}** updated.",
            color=GREEN
        )
    )


# ── /viewdropstock ────────────────────────────────────────────────────────────

@bot.tree.command(name="viewdropstock", description="View the drop stock count.")
async def viewdropstock(interaction: discord.Interaction):
    count = await db.get_drop_stock_count(str(interaction.guild_id))
    embed = discord.Embed(title="🎁 Drop Stock", color=BLUE)
    embed.add_field(name="Available", value=str(count), inline=False)
    embed.set_footer(text="DOKKAEBI 💎")
    await interaction.response.send_message(embed=embed)


# ── /adddropstock ─────────────────────────────────────────────────────────────

@bot.tree.command(name="adddropstock", description="Add accounts to the drop stock. (Admin)")
@app_commands.describe(accounts="Accounts to add, one per line")
@is_admin()
async def adddropstock(interaction: discord.Interaction, accounts: str):
    lines = [l.strip() for l in accounts.strip().splitlines() if l.strip()]
    if not lines:
        await interaction.response.send_message(
            embed=discord.Embed(description="❌ No valid accounts provided.", color=RED), ephemeral=True
        )
        return
    await db.add_drop_stock(str(interaction.guild_id), lines)
    await interaction.response.send_message(
        embed=discord.Embed(
            title="✅ Drop Stock Added",
            description=f"Added **{len(lines)}** accounts to drop stock.",
            color=GREEN
        )
    )


# ── Drop task ─────────────────────────────────────────────────────────────────

async def run_drop(guild: discord.Guild):
    guild_id = str(guild.id)
    while True:
        cooldown_str = await db.get_config(guild_id, "drop_cooldown")
        cooldown = int(cooldown_str) if cooldown_str else 60
        await asyncio.sleep(cooldown)

        ch_id = await db.get_config(guild_id, "drop_channel")
        if not ch_id:
            continue
        ch = guild.get_channel(int(ch_id))
        if not ch:
            continue

        account = await db.pop_drop_stock(guild_id)
        if not account:
            embed = discord.Embed(
                title="🎁 Drop",
                description="No more accounts in drop stock!",
                color=RED
            )
            await ch.send(embed=embed)
            bot.drop_tasks.pop(guild.id, None)
            return

        embed = discord.Embed(
            title="🎁 Account Drop!",
            description=f"A free account has been dropped!\n```{account}```",
            color=GOLD
        )
        embed.set_footer(text="DOKKAEBI 💎 • First come, first served!")
        await ch.send(embed=embed)


# ── /dropstart ────────────────────────────────────────────────────────────────

@bot.tree.command(name="dropstart", description="Start the account drop. (Admin)")
@is_admin()
async def dropstart(interaction: discord.Interaction):
    guild = interaction.guild
    if guild.id in bot.drop_tasks and not bot.drop_tasks[guild.id].done():
        await interaction.response.send_message(
            embed=discord.Embed(description="⚠️ A drop is already running!", color=RED), ephemeral=True
        )
        return
    count = await db.get_drop_stock_count(str(guild.id))
    if count == 0:
        await interaction.response.send_message(
            embed=discord.Embed(description="❌ Drop stock is empty. Use `/adddropstock` first.", color=RED), ephemeral=True
        )
        return
    bot.drop_tasks[guild.id] = asyncio.create_task(run_drop(guild))
    cooldown_str = await db.get_config(str(guild.id), "drop_cooldown")
    cooldown = int(cooldown_str) if cooldown_str else 60
    await interaction.response.send_message(
        embed=discord.Embed(
            title="▶️ Drop Started",
            description=f"Dropping accounts every **{cooldown}s**. Stock: **{count}** accounts.",
            color=GREEN
        )
    )


# ── /dropstop ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="dropstop", description="Stop the active drop. (Admin)")
@is_admin()
async def dropstop(interaction: discord.Interaction):
    task = bot.drop_tasks.pop(interaction.guild_id, None)
    if task and not task.done():
        task.cancel()
        await interaction.response.send_message(
            embed=discord.Embed(title="⏹️ Drop Stopped", description="The drop has been stopped.", color=RED)
        )
    else:
        await interaction.response.send_message(
            embed=discord.Embed(description="⚠️ No drop is currently running.", color=RED), ephemeral=True
        )


# ── /dropstatus ───────────────────────────────────────────────────────────────

@bot.tree.command(name="dropstatus", description="Check the drop status.")
async def dropstatus(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    running  = interaction.guild_id in bot.drop_tasks and not bot.drop_tasks[interaction.guild_id].done()
    count    = await db.get_drop_stock_count(guild_id)
    cooldown_str = await db.get_config(guild_id, "drop_cooldown")
    cooldown = int(cooldown_str) if cooldown_str else 60
    ch_id    = await db.get_config(guild_id, "drop_channel")
    ch_mention = f"<#{ch_id}>" if ch_id else "Not set"

    embed = discord.Embed(title="🎁 Drop Status", color=GREEN if running else RED)
    embed.add_field(name="Status",   value="🟢 Running" if running else "🔴 Stopped", inline=True)
    embed.add_field(name="Stock",    value=str(count),    inline=True)
    embed.add_field(name="Cooldown", value=f"{cooldown}s", inline=True)
    embed.add_field(name="Channel",  value=ch_mention,    inline=True)
    embed.set_footer(text="DOKKAEBI 💎")
    await interaction.response.send_message(embed=embed)


# ── /dropcooldown ─────────────────────────────────────────────────────────────

@bot.tree.command(name="dropcooldown", description="View or set the drop interval in seconds. (Admin)")
@app_commands.describe(seconds="Seconds between drops (leave empty to view current)")
async def dropcooldown(interaction: discord.Interaction, seconds: int | None = None):
    guild_id = str(interaction.guild_id)
    if seconds is None:
        cur = await db.get_config(guild_id, "drop_cooldown")
        await interaction.response.send_message(
            embed=discord.Embed(
                title="⏱️ Drop Cooldown",
                description=f"Current: **{cur or 60}s**",
                color=BLUE
            )
        )
        return
    if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            embed=discord.Embed(description="❌ Administrator permission required.", color=RED), ephemeral=True
        )
        return
    await db.set_config(guild_id, "drop_cooldown", str(seconds))
    await interaction.response.send_message(
        embed=discord.Embed(
            title="⏱️ Drop Cooldown Set",
            description=f"Drop interval set to **{seconds}s**.",
            color=GREEN
        )
    )


# ── /setcooldown ──────────────────────────────────────────────────────────────

@bot.tree.command(name="setcooldown", description="Set the generate command cooldown. (Admin)")
@app_commands.describe(seconds="Cooldown in seconds between generates")
@is_admin()
async def setcooldown(interaction: discord.Interaction, seconds: int):
    await db.set_config(str(interaction.guild_id), "gen_cooldown", str(seconds))
    await interaction.response.send_message(
        embed=discord.Embed(
            title="⏱️ Generate Cooldown Set",
            description=f"Generate cooldown set to **{seconds}s**.",
            color=GREEN
        )
    )


# ── /setchannel ───────────────────────────────────────────────────────────────

channel_types = [
    app_commands.Choice(name="drop",    value="drop_channel"),
    app_commands.Choice(name="gen-log", value="gen_log_channel"),
    app_commands.Choice(name="vouch",   value="vouch_channel"),
    app_commands.Choice(name="log",     value="log_channel"),
]

@bot.tree.command(name="setchannel", description="Set a bot channel. (Admin)")
@app_commands.describe(channel_type="The channel type to set", channel="The channel to assign")
@app_commands.choices(channel_type=channel_types)
@is_admin()
async def setchannel(
    interaction: discord.Interaction,
    channel_type: app_commands.Choice[str],
    channel: discord.TextChannel
):
    await db.set_config(str(interaction.guild_id), channel_type.value, str(channel.id))
    await interaction.response.send_message(
        embed=discord.Embed(
            title="📌 Channel Set",
            description=f"**{channel_type.name}** channel set to {channel.mention}.",
            color=GREEN
        )
    )


# ── /checkchannel ─────────────────────────────────────────────────────────────

@bot.tree.command(name="checkchannel", description="View all configured channels.")
async def checkchannel(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    keys = {
        "drop_channel":     "🎁 Drop",
        "gen_log_channel":  "🔫 Gen Log",
        "vouch_channel":    "⭐ Vouch",
        "log_channel":      "📋 Log",
    }
    embed = discord.Embed(title="📌 Configured Channels", color=BLUE)
    for key, label in keys.items():
        val = await db.get_config(guild_id, key)
        embed.add_field(name=label, value=f"<#{val}>" if val else "Not set", inline=True)
    embed.set_footer(text="DOKKAEBI 💎")
    await interaction.response.send_message(embed=embed)


# ── /setsubscription ──────────────────────────────────────────────────────────

@bot.tree.command(name="setsubscription", description="Set a user's subscription tier. (Admin)")
@app_commands.describe(user="The user to update", tier="Subscription tier")
@app_commands.choices(tier=[
    app_commands.Choice(name="Free",    value="Free"),
    app_commands.Choice(name="Premium", value="Premium"),
    app_commands.Choice(name="None",    value="None"),
])
@is_admin()
async def setsubscription(
    interaction: discord.Interaction,
    user: discord.Member,
    tier: app_commands.Choice[str]
):
    guild_id = str(interaction.guild_id)
    guild    = interaction.guild

    # Fetch the premium role if one has been configured via /setrole
    premium_role_id  = await db.get_config(guild_id, "premium_role")
    free_role_id     = await db.get_config(guild_id, "free_role")
    premium_role     = guild.get_role(int(premium_role_id)) if premium_role_id else None
    free_role        = guild.get_role(int(free_role_id))    if free_role_id    else None

    # ── Remove subscription ───────────────────────────────────────────────────
    if tier.value == "None":
        await db.remove_subscription(guild_id, str(user.id))

        # Strip both tier roles if the member has them
        roles_to_remove = [r for r in [premium_role, free_role] if r and r in user.roles]
        if roles_to_remove:
            try:
                await user.remove_roles(*roles_to_remove, reason="Subscription removed")
            except discord.Forbidden:
                pass

        # DM the user
        removed_embed = discord.Embed(
            title="❌ Subscription Removed",
            description=f"Your subscription in **{guild.name}** has been removed.",
            color=RED
        )
        removed_embed.set_footer(text="DOKKAEBI 💎")
        try:
            await user.send(embed=removed_embed)
        except discord.Forbidden:
            pass  # DMs closed

        await interaction.response.send_message(
            embed=discord.Embed(
                title="💎 Subscription Removed",
                description=f"Removed subscription from {user.mention}.",
                color=RED
            )
        )
        return

    # ── Set subscription ──────────────────────────────────────────────────────
    await db.set_subscription(guild_id, str(user.id), tier.value)

    # Assign the matching role and remove the opposite one
    if tier.value == "Premium":
        role_to_add    = premium_role
        role_to_remove = free_role
    else:
        role_to_add    = free_role
        role_to_remove = premium_role

    role_errors = []
    try:
        if role_to_add and role_to_add not in user.roles:
            await user.add_roles(role_to_add, reason=f"Subscription set to {tier.value}")
        if role_to_remove and role_to_remove in user.roles:
            await user.remove_roles(role_to_remove, reason=f"Subscription changed to {tier.value}")
    except discord.Forbidden:
        role_errors.append("⚠️ I don't have permission to manage roles.")

    # ── DM the user ───────────────────────────────────────────────────────────
    image_url = await db.get_config(guild_id, "gen_image_url")

    dm_embed = discord.Embed(
        title="💎 Subscription Activated" if tier.value == "Premium" else "🆓 Subscription Activated",
        color=GOLD if tier.value == "Premium" else GREEN
    )
    dm_embed.add_field(name="Server",  value=guild.name,   inline=True)
    dm_embed.add_field(name="Tier",    value=f"{'💎 Premium' if tier.value == 'Premium' else '🆓 Free'}", inline=True)
    if role_to_add:
        dm_embed.add_field(name="Role Granted", value=role_to_add.name, inline=True)
    dm_embed.add_field(
        name="What's next?",
        value=f"You can now use `/generate category:{tier.value}` in **{guild.name}**!",
        inline=False
    )
    if image_url:
        dm_embed.set_image(url=image_url)
    dm_embed.set_footer(text="DOKKAEBI 💎")

    dm_status = ""
    try:
        await user.send(embed=dm_embed)
        dm_status = "✅ DM sent."
    except discord.Forbidden:
        dm_status = "⚠️ Could not DM user (DMs may be closed)."

    # ── Confirm to admin ──────────────────────────────────────────────────────
    confirm_embed = discord.Embed(
        title="💎 Subscription Updated",
        description=f"Set {user.mention}'s subscription to **{tier.value}**.",
        color=GOLD if tier.value == "Premium" else GREEN
    )
    if role_to_add:
        confirm_embed.add_field(name="Role Granted", value=role_to_add.mention, inline=True)
    confirm_embed.add_field(name="DM", value=dm_status, inline=True)
    if role_errors:
        confirm_embed.add_field(name="Warning", value="\n".join(role_errors), inline=False)
    confirm_embed.set_footer(text="DOKKAEBI 💎")
    await interaction.response.send_message(embed=confirm_embed)


# ── /checksub ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="checksub", description="Check a user's subscription.")
@app_commands.describe(user="User to check (defaults to yourself)")
async def checksub(interaction: discord.Interaction, user: discord.Member | None = None):
    target   = user or interaction.user
    guild_id = str(interaction.guild_id)
    tier     = await db.get_subscription(guild_id, str(target.id))
    embed = discord.Embed(title="💎 Subscription Status", color=GOLD if tier == "Premium" else BLUE)
    embed.add_field(name="User", value=target.mention, inline=True)
    embed.add_field(name="Tier", value=tier or "None", inline=True)
    embed.set_footer(text="DOKKAEBI 💎")
    await interaction.response.send_message(embed=embed)


# ── /vouch ────────────────────────────────────────────────────────────────────

@bot.tree.command(name="vouch", description="Vouch for a user.")
@app_commands.describe(user="User to vouch for", message="Your vouch message")
async def vouch(interaction: discord.Interaction, user: discord.Member, message: str):
    guild_id = str(interaction.guild_id)
    if user.id == interaction.user.id:
        await interaction.response.send_message(
            embed=discord.Embed(description="❌ You cannot vouch for yourself.", color=RED), ephemeral=True
        )
        return
    await db.add_vouch(guild_id, str(user.id), str(interaction.user.id), message)
    count = await db.get_vouch_count(guild_id, str(user.id))

    embed = discord.Embed(
        title="⭐ Vouch Added",
        description=f"{interaction.user.mention} vouched for {user.mention}!\n\n*\"{message}\"*",
        color=GOLD
    )
    embed.add_field(name="Total Vouches", value=str(count), inline=True)
    embed.set_footer(text="DOKKAEBI 💎")
    await interaction.response.send_message(embed=embed)

    # Send to vouch channel if set
    ch_id = await db.get_config(guild_id, "vouch_channel")
    if ch_id:
        ch = interaction.guild.get_channel(int(ch_id))
        if ch and ch.id != interaction.channel_id:
            await ch.send(embed=embed)


# ── /invites ──────────────────────────────────────────────────────────────────

@bot.tree.command(name="invites", description="Check your invite count.")
@app_commands.describe(user="User to check (defaults to yourself)")
async def invites(interaction: discord.Interaction, user: discord.Member | None = None):
    target   = user or interaction.user
    guild_id = str(interaction.guild_id)
    count    = await db.get_invite_count(guild_id, str(target.id))
    embed = discord.Embed(
        title="📨 Invites",
        description=f"{target.mention} has **{count}** invite(s).",
        color=BLUE
    )
    embed.set_footer(text="DOKKAEBI 💎")
    await interaction.response.send_message(embed=embed)


# ── /createinvite ─────────────────────────────────────────────────────────────

@bot.tree.command(name="createinvite", description="Create a server invite link.")
async def createinvite(interaction: discord.Interaction):
    try:
        invite = await interaction.channel.create_invite(max_age=0, max_uses=0, unique=True)
        embed = discord.Embed(
            title="📨 Invite Created",
            description=f"Here is your invite link:\n{invite.url}",
            color=GREEN
        )
        embed.set_footer(text="DOKKAEBI 💎")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=discord.Embed(description="❌ I don't have permission to create invites.", color=RED),
            ephemeral=True
        )


# ── /inviteleaderboard ────────────────────────────────────────────────────────

@bot.tree.command(name="inviteleaderboard", description="Show the top inviters.")
async def inviteleaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    guild_id = str(interaction.guild_id)
    rows = await db.get_invite_leaderboard(guild_id, limit=10)
    embed = discord.Embed(title="🏆 Invite Leaderboard", color=GOLD)
    if not rows:
        embed.description = "No invite data yet."
    else:
        lines = []
        for i, (uid, total) in enumerate(rows, 1):
            try:
                member = interaction.guild.get_member(int(uid)) or await interaction.guild.fetch_member(int(uid))
                name = member.display_name
            except Exception:
                name = f"User {uid}"
            lines.append(f"**{i}.** {name} — **{total}** invite(s)")
        embed.description = "\n".join(lines)
    embed.set_footer(text="DOKKAEBI 💎")
    await interaction.followup.send(embed=embed)


# ── /refreshinvites ───────────────────────────────────────────────────────────

@bot.tree.command(name="refreshinvites", description="Refresh the invite cache. (Admin)")
@is_admin()
async def refreshinvites(interaction: discord.Interaction):
    await bot._cache_invites(interaction.guild)
    await interaction.response.send_message(
        embed=discord.Embed(
            title="🔄 Invites Refreshed",
            description="Invite cache has been refreshed.",
            color=GREEN
        )
    )


# ── /messages ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="messages", description="Check your message count.")
@app_commands.describe(user="User to check (defaults to yourself)")
async def messages(interaction: discord.Interaction, user: discord.Member | None = None):
    target   = user or interaction.user
    guild_id = str(interaction.guild_id)
    count    = await db.get_message_count(guild_id, str(target.id))
    embed = discord.Embed(
        title="💬 Message Count",
        description=f"{target.mention} has sent **{count}** message(s) in this server.",
        color=BLUE
    )
    embed.set_footer(text="DOKKAEBI 💎")
    await interaction.response.send_message(embed=embed)


# ── Run ───────────────────────────────────────────────────────────────────────

bot.run(TOKEN)

import logging
import discord
import time
import random
import asyncio
import datetime
from discord.ext import commands
import json
import subprocess

from discord.partial_emoji import PartialEmoji

logging.basicConfig(filename='verification.log', filemode='w', format='%(asctime)s - %(levelname)s - %(message)s',level=logging.INFO,datefmt='%Y-%m-%d %H:%M:%S') # Logs to verification.log file
with open("config.json", "r") as read: # Imports config json file
    config_json = json.load(read)


# Static variables
token = config_json["token"]
home_server_ID = int(config_json["homeserver_id"])

verification_requirement_join = int(config_json["verification_requirement_join"])

verification_requirement_message = int(config_json["verification_requirement_message"])

moderator_mail = int(config_json["moderator_mail_id"])

log_channel_ID = int(config_json["log_channel_id"])

unboost_channel_ID = int(config_json["unboost_announcement_channel_id"])

status = config_json["status"]

colored_roles = config_json["colored_roles"]
colored_roles = [int(c) for c in colored_roles] # Making sure they are ints


prefix = config_json["prefix"]

moderator_role_IDs = config_json["moderator_role_IDs"]
moderator_role_IDs = [int(m) for m in moderator_role_IDs] # Making sure they are ints


verified_role = int(config_json["verified_role"])

emergency_request_approval_threshold = int(config_json["emergency_request_approval_threshold"])

emergency_request_deny_threshold = int(config_json["emergency_request_deny_threshold"])

emergency_request_deny_threshold = int(config_json["emergency_request_deny_threshold"])

ontopic_category_id = int(config_json["ontopic_category_id"])

emergency_role_id = int(config_json["emergency_role_id"])

emergency_role_reminder = int(config_json["emergency_role_reminder"])

emergency_role_timeout = int(config_json["emergency_role_timeout"])

emergency_top_role_bypass_id = config_json["emergency_top_role_bypass_id"]
emergency_top_role_bypass_id = [int(m) for m in emergency_top_role_bypass_id] # Making sure they are ints

birthday_role_id = int(config_json["birthday_role_ID"])

irc_relay_container_id = str(config_json["irc_relay_id"])

colors = [discord.Colour.purple(), discord.Colour.blue(), discord.Colour.red(), discord.Colour.green(), discord.Colour.orange()] # Discord colors for embedding

uptime_start = datetime.datetime.now(datetime.timezone.utc)



# Enable intents
intents = discord.Intents.all()
intents.members = True


# Logging in to the bot

client = commands.Bot(command_prefix=prefix,activity=discord.Activity(type=discord.ActivityType.playing), name=status, intents=intents)



@client.event
async def on_ready():
    print('Logged in as {0.user}'.format(client))
    logging.info('Logged in as {0.user}'.format(client))


# Ontopic category checker function (checks if the category of the channel is in the on-topic section)
def ontopic(ctx):
    return ctx.channel.category.id == ontopic_category_id

def cleanup_emergency(): # Function to cleanup once an emergency is over
    client.approved_list.clear()
    client.denied_list.clear()
    client.emergency_active = None
    client.emergency_caller_object = None
    client.bot_emergency_message = None
    client.bot_emergency_message_link = None
    client.bot_emergency_reminder_count = 0


# Variables for the emergency command to be used across multiple functions
client.emergency_active = None # Boolean for knowing if there is an active emergency request
client.approved_list = [] # List of people who have approved the emergency
client.denied_list = [] # List of people who have denied the emergency
client.emergency_caller_object = None # Bot variable that tracks the object of whoever sent the !emergency message
client.bot_emergency_message = None # Object for the emergency that the bot sends
client.bot_emergency_message_link = None
client.bot_emergency_reminder_count = 0




# Verification functions
@client.event
async def on_message(message):

    if message.author == client.user: # Ignores the bots own messages
        return

    if message.guild is None:
        logging.info("Direct message received: %s - sent by %s (ID: %d)"% (message.content.lower(),message.author.name, message.author.id))
        if "verify" in message.content.lower() or "verified" in message.content.lower():
            author_id = int(message.author.id) # Author's ID
            account_age = datetime.datetime.now(datetime.timezone.utc) - message.author.created_at # Subtracts current time with account creation date to get account age
            account_age_days = account_age.days # Account age in days
            home_server = client.get_guild(home_server_ID) # Gets the guild
            log_channel = client.get_channel(log_channel_ID) # #logs channel
            home_server_info = home_server.get_member(author_id) # Fetches user info from said guild
            home_server_top_role = str(home_server_info.top_role.name) # Fetches top role from user info
            home_server_verified_role = home_server.get_role(verified_role) # The ID of the role that the bot gives in order for the person to be able to use the server
            if home_server_top_role == "@everyone":
                if account_age_days < verification_requirement_message:
                    await message.channel.send("Sorry, your account must be 5 days or older in order to get verified. Please either verify with your phone number or contact the mod team through <@%s> (Moderator mail, top of the member list) for manual verification if you're unable to verify with a phone number."% str(moderator_mail))
                    logembedfail = discord.Embed(description='<@%d> (%s) attempted to get manually verified, however his account age is too low (%d days)'% (int(author_id), str(author_id), account_age_days),timestamp=datetime.datetime.now(datetime.timezone.utc),color=discord.Colour.red())
                    logembedfail.set_author(name=message.author.name, icon_url=message.author.avatar.url)
                    logging.info(message.author.name + "(%d) attempted to get manually verified, but his account age was too low (%d days)"% (author_id, account_age_days))
                    await log_channel.send(embed=logembedfail)
                    return
                elif account_age_days >= verification_requirement_message:
                    await home_server_info.add_roles(home_server_verified_role, reason="User has manually been verified with Verification bot. Account age: %d days" % account_age_days) # Adds unverified role to the user
                    log_embed = discord.Embed(description="<@%d> has been verified"% author_id,timestamp=datetime.datetime.now(datetime.timezone.utc),color=discord.Colour.green())
                    log_embed.set_author(name=message.author.name, icon_url=message.author.avatar.url)
                    await log_channel.send(embed=log_embed)
                    await message.channel.send("You have been verified. Please remember to read the <#%s>. You may also assign yourself roles in <#%s>. If you ever have an issue, do not hesitate to message <@%s> (Moderator Mail, top of the member list)"% (str(448941767325253632),str(516816975427797012),str(moderator_mail)))
                    await message.add_reaction('✅')
                    logging.info(message.author.name + " (%d) has been verified. Account age: %d days" % (author_id,account_age_days))
                    return
            else:
                await message.channel.send("You're already able to speak in the server, there is no need for you to get verified. Contact <@%s> (Moderator Mail, top of the member list) if there is an issue."% str(moderator_mail))
                logging.info(message.author.name + " (%d) attempted to get verified, but doesn't have @ everyone as his top role. Verification aborted."% author_id)
                return
    await client.process_commands(message)




# Event to automatically verify people with account ages over 3 months old
@client.event
async def on_member_join(member):
    member_id = int(member.id)
    account_age = datetime.datetime.now(datetime.timezone.utc) - member.created_at # Subtracts current time with account creation date to get account age
    account_age_days = account_age.days # Account age in days
    home_server = client.get_guild(home_server_ID) # Gets the guild
    log_channel = client.get_channel(log_channel_ID) # #logs channel
    home_server_info = home_server.get_member(member_id) # Fetches user info from said guild
    home_server_verified_role = home_server.get_role(verified_role) # The ID of the role that the bot gives in order for the person to be able to use the server
    if account_age_days > verification_requirement_join:
        await home_server_info.add_roles(home_server_verified_role, reason="Account age is over 3 months (%d days), user has automatically been verified."% account_age_days) # Adds unverified role to the user
        log_embed = discord.Embed(description="<@%d> has been verified automatically because his account age is over 3 months (%d days)"% (member_id,account_age_days),timestamp=datetime.datetime.now(datetime.timezone.utc),color=discord.Colour.green())
        log_embed.set_author(name=member.id, icon_url=member.avatar.url)
        await log_channel.send(embed=log_embed)
        logging.info("%s (%d) has been verified automatically because his account age is over 3 months (%d days)"% (str(member.name),member_id,account_age_days))
        return



# Event to remove colored roles when a member unboosts and to also msg a user if he boosts
@client.event
async def on_member_update(member,updatedmember):
    check_boost = member.premium_since
    check_if_unboost = updatedmember.premium_since
    member_id = member.id # Members ID
    if check_boost is not None:
        if check_if_unboost is None:
            logging.info("{0} ({1}) unboosted the server.".format(member.name,member_id))
            home_server = client.get_guild(home_server_ID)
            log_channel_unboost = client.get_channel(unboost_channel_ID) # #logs channel
            log_embed_unboost = discord.Embed(description="{0} ({1}) unboosted the server.".format(member.mention,member.id),timestamp=datetime.datetime.now(datetime.timezone.utc),color=discord.Colour.red())
            log_embed_unboost.set_author(name=member.name, icon_url=member.avatar.url)
            await log_channel_unboost.send(embed=log_embed_unboost)
            for role in colored_roles:
                role = home_server.get_role(role)
                await updatedmember.remove_roles(role, reason="User unboosted the server, colors have been removed")
    if check_boost is None:
        if check_if_unboost is not None:
            logging.info("{0} ({1}) boosted the server.".format(member.name,member_id))
            await member.send("Thank you for boosting /r/sysadmin! As a booster you have access to a new channel (<#585867795942604800>) as well as being" \
            " able to choose from a variety of colored roles. Check the <#516816975427797012> channel for more info on getting a colored role!\n If you have any questions feel free" \
            " to message Moderator Mail (top of the member list)")





# Bot commands
@client.command(name='steve')
@commands.cooldown(1,10,commands.BucketType.member)
async def steve(ctx):
    stevelist = ['<:steve1:418736567373266955>','<:steve2:418736568145149952>', '<:steve3:418736567922851851>', '<:steve4:418736568040292352>','<:steve5:418736568057069569>']
    steves = stevelist[0] + '\n' + stevelist[1] + '\n' + stevelist[2] + '\n' + stevelist[3] + '\n' + stevelist[4]
    steve = discord.Embed(color=random.choice(colors), description=steves)
    await ctx.send(embed=steve)



@client.command(name='ping')
@commands.cooldown(1,10,commands.BucketType.member)
async def ping(ctx):
    pingem = discord.Embed(color=random.choice(colors))
    pingem.add_field(name=':ping_pong: Ping', value=':ping_pong: Pong')
    pingem.add_field(name=':newspaper: Response time', value=f'{client.latency * 1000:.0f} ms')
    await ctx.send(embed=pingem)


@client.command(name='birthday')
@commands.has_any_role(*moderator_role_IDs)
async def birthday(ctx, birthdayboy: discord.Member):
    home_server_info = client.get_guild(home_server_ID)
    birthday_role = home_server_info.get_role(birthday_role_id)
    log_channel = home_server_info.get_channel(log_channel_ID)
    birthday_embed = discord.Embed(color=discord.Colour.purple(),timestamp=datetime.datetime.now(datetime.timezone.utc))
    birthday_embed.set_author(name=birthdayboy.name,icon_url=birthdayboy.avatar.url)
    birthday_embed.set_footer(text="Responsible user: {0}".format(ctx.author.name),icon_url=ctx.author.avatar.url)
    if birthday_role in birthdayboy.roles:
        await birthdayboy.remove_roles(birthday_role,reason="Responsible user: %s" % ctx.author.name)
        birthday_embed.description = "{0} removed the birthday boy role from {1}".format(ctx.author.name,birthdayboy.name)
        birthday_embed.title = "Birthday boy role removed"
        await log_channel.send(birthday_embed)
    else:
        await birthdayboy.add_roles(birthday_role,reason="Responsible user: %s" % ctx.author.name)
        await ctx.send("Gave the birthday boy role to <@%d>. Automatically removing it in 12 hours." % birthdayboy.id)
        birthday_embed.description = "{0} added the birthday boy role to {1}".format(ctx.author.name,birthdayboy.name)
        birthday_embed.title = "Birthday boy role added"
        await log_channel.send(birthday_embed)
        await asyncio.sleep(64800)
        if birthday_role in birthdayboy.roles:
            await birthdayboy.remove_roles(birthday_role,reason="Responsible user: {0}".format(ctx.author.name))
            birthday_embed.description = "{0} removed the birthday boy role from {1}".format(ctx.author.name,birthdayboy.name)
            birthday_embed.title = "Birthday boy role removed"
            await log_channel.send(birthday_embed)


@client.command(name='boosters')
@commands.cooldown(1, 15, commands.BucketType.channel)
async def boosters(ctx):
    home_server_info = client.get_guild(home_server_ID)
    boosters_list = home_server_info.premium_subscribers
    boosters_list.sort(key=lambda b: b.premium_since)  # Sorts boosters from oldest to most recent
    booster_embed = discord.Embed(
        title="There are currently {0} people boosting the server. Current tier: {1}".format(
            home_server_info.premium_subscription_count, home_server_info.premium_tier
        ),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        color=discord.Colour.blue()
    )
    booster_embed.set_footer(text="queried by {0}".format(ctx.author.name), icon_url=ctx.author.avatar.url)  # Corrected line
    booster_embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url)
    for booster in boosters_list:
        booster_embed.add_field(
            name="{0}, joined {1}".format(booster.name, booster.joined_at.strftime("%b %d %Y")),
            value="{0} - Boosting since: {1}".format(booster.mention, booster.premium_since.strftime("%b %d %Y")),
            inline=False
        )
    await ctx.send(embed=booster_embed)



@client.command(name='uptime')
@commands.cooldown(1,10,commands.BucketType.user)
async def uptime(ctx):
    uptime_end = datetime.datetime.now(datetime.timezone.utc) - uptime_start
    uptime_embed = discord.Embed(timestamp=datetime.datetime.now(datetime.timezone.utc),color=random.choice(colors))
    uptime_embed.set_author(name=client.user.name, icon_url=client.user.avatar.url)
    uptime_embed.set_footer(text="queried by {0}".format(ctx.author.name),icon_url=ctx.author.avatar.url)
    uptime_embed.add_field(name="Current uptime",value="{0.days} days {1} hours {2} minutes".format(uptime_end,uptime_end.seconds//3600,(uptime_end.seconds//60)%60)) # Fix seconds
    await ctx.send(embed=uptime_embed)
    logging.info("{0.author.name} ({0.author.id} used uptime command in {0.channel.name} ({0.channel.id}))".format(ctx))


@client.command(name='github')
@commands.cooldown(1, 10, commands.BucketType.user)
async def github(ctx):
    github_embed = discord.Embed(timestamp=datetime.datetime.now(datetime.timezone.utc))  # Create the embed without the 'colors' argument
    github_embed.color = random.choice(colors)  # Set the color after creation
    github_embed.set_author(name="github.com/mmcmd", icon_url="https://avatars1.githubusercontent.com/u/36875145")
    github_embed.set_footer(text="queried by {0}".format(ctx.author.name), icon_url=ctx.author.avatar.url)
    github_embed.add_field(name="The source code of this bot can be found at:", value="https://github.com/mmcmd/verification-bot")
    await ctx.send(embed=github_embed)


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):

    if payload.member == client.user: # Ignores the bots own messages
        return

    if payload.message_id != client.bot_emergency_message.id: # Ignores the reaction if it's not a reaction to the bot msg
        return

    if payload.member.id == client.emergency_caller_object.author.id:
        return

    guild = client.get_guild(payload.guild_id)
    log_channel = client.get_channel(log_channel_ID) # #logs channel
    emergency_channel = guild.get_channel(client.emergency_caller_object.channel.id)
    verified_role_object = guild.get_role(verified_role)


    if guild is None:
        # Check if we're still in the guild and it's cached
        return

    if (payload.emoji.name != "✅") and (payload.emoji.name != "❌"): # Ignores any emoji that do not correspond to these two
        return


    if payload.member.top_role.id == verified_role_object.id: # Ignores the users reaction if the user is not above verified
        return



    if payload.emoji.name == '✅':
        client.approved_list.append(payload.user_id)
        log_embed = discord.Embed(title='Emergency request approved',description="{0.mention} has approved emergency request {1} ({2}/{3})".format(payload.member,client.bot_emergency_message.id,len(client.approved_list),emergency_request_approval_threshold),timestamp=datetime.datetime.now(datetime.timezone.utc),color=discord.Colour.green())
        log_embed.add_field(name="Link to message",value=client.bot_emergency_message_link)
        await log_channel.send(embed=log_embed)
        logging.info("{0.mention} ({0.id}) has approved emergency request {1}".format(payload.member,client.bot_emergency_message.id))
        await client.bot_emergency_message.edit(content="An emergency has been called by {0}.\nVerification is needed by at least {2} other members of sudo level 1 or higher to validate that this is indeed an emergency." \
                                          " If you're sudo 1 or above and deem this an emergency, react with the ✅ emoji. If this does not qualify as an emergency, react with ❌. \n \n" \
                                          "**Make sure all the details about the incident are clear and you have elaborated clearly on what the issue actually is!** \n \n" \
                                          "__Reminder that the emergency ping is reserved for business production issues that are extremely time sensitive, not for homework or any other non-emergency issue.__ \n \n"
                                          "Approved: {1}/{2} \n \n Denied: {3}/{4}".format(client.emergency_caller_object.author.mention,len(client.approved_list),emergency_request_approval_threshold,len(client.denied_list),emergency_request_deny_threshold))

        # Threshold reached for emergency approval, emergency approved
        if len(client.approved_list) == emergency_request_approval_threshold:
            emergency_role_object = guild.get_role(emergency_role_id)
            await emergency_channel.send("The emergency called by {0.author.mention} has been approved.\n \nLink to message: " \
                                            "https://discord.com/channels/{1.id}/{2}/{3} \n \n {4.mention}".format(client.emergency_caller_object,guild,client.emergency_caller_object.channel.id,client.bot_emergency_message.id,emergency_role_object))
            cleanup_emergency()



    if payload.emoji.name == '❌':
        client.denied_list.append(payload.user_id)
        log_embed = discord.Embed(title='Emergency request denied',description="{0.mention} has denied emergency request {1} ({2}/{3})".format(payload.member,client.bot_emergency_message.id,len(client.denied_list),emergency_request_deny_threshold),timestamp=datetime.datetime.now(datetime.timezone.utc),color=discord.Colour.green())
        log_embed.add_field(name="Link to message",value=client.bot_emergency_message_link)
        await log_channel.send(embed=log_embed)
        logging.info("{0.mention} ({0.id}) has denied emergency request {1}".format(payload.member,client.bot_emergency_message.id))
        await client.bot_emergency_message.edit(content="An emergency has been called by {0}.\nVerification is needed by at least {2} other members of sudo level 1 or higher to validate that this is indeed an emergency." \
                                          " If you're sudo 1 or above and deem this an emergency, react with the ✅ emoji. If this does not qualify as an emergency, react with ❌. \n \n" \
                                          "**Make sure all the details about the incident are clear and you have elaborated clearly on what the issue actually is!** \n \n" \
                                            "__Reminder that the emergency ping is reserved for business production issues that are extremely time sensitive, not for homework or any other non-emergency issue.__ \n \n"
                                          "Approved: {1}/{2} \n \n Denied: {3}/{4}".format(client.emergency_caller_object.author.mention,len(client.approved_list),emergency_request_approval_threshold,len(client.denied_list),emergency_request_deny_threshold))

        # Threshold reached for emergency denial, emergency denied
        if len(client.denied_list) == emergency_request_deny_threshold:
            await emergency_channel.send("{0.author.mention}, your emergency has been denied. Reminder that the emergency ping is reserved for"
                                         " business production issues that are extremely time sensitive, not for homework or any other non-emergency "
                                         "issue.".format(client.emergency_caller_object))
            cleanup_emergency()




@client.command(name='emergency')
@commands.cooldown(1,120,commands.BucketType.guild)
@commands.has_role(verified_role)
@commands.check(ontopic)
@commands.guild_only()
async def emergency(ctx):

    client.emergency_caller_object = ctx
    guild = client.get_guild(ctx.guild.id)
    log_channel = guild.get_channel(log_channel_ID)
    emergency_role_object = ctx.guild.get_role(emergency_role_id)
    bypass_roles = []
   
    for role_id in emergency_top_role_bypass_id:
        bypass_roles.append((ctx.guild.get_role(role_id)))
    

    if client.emergency_active == True:
        await ctx.channel.send("There is already an emergency active. To clear it, ask a mod or <@{0}> to type `{2}clearemergency` or deny/approve the existing one." \
                                "\n \n Link to the current emergency: {1}".format(moderator_mail,client.bot_emergency_message_link,prefix))
        return

    if any(role in ctx.author.roles for role in bypass_roles):  # Check for any matching role
        await ctx.send("An emergency is being called by {0.author.mention}.\n \n {1.mention}\n \n"
              "**{0.author.mention}, make sure to provide all necessary info (screenshots if possible, things you've tried already, and any other details people might need to know).**"
              .format(ctx, emergency_role_object))
        emergency_embed = discord.Embed(title="Emergency called",timestamp=datetime.datetime.now(datetime.timezone.utc),color=random.choice(colors))
        emergency_embed.description = "{0.author.mention} ({0.author.id}) used the emergency command in {0.channel.name} (<#{0.channel.id}>))".format(ctx)
        emergency_embed.add_field(name="Link to message",value="https://discord.com/channels/{0.id}/{1}/{2}".format(guild,ctx.channel.id,ctx.message.id))
        await log_channel.send(embed=emergency_embed)
        return


    client.emergency_active = True
    client.bot_emergency_message = await ctx.send(("An emergency has been called by {0}.\nVerification is needed by at least {2} other members of sudo level 1 or higher to validate that this is indeed an emergency." \
                                            " If you're sudo 1 or above and deem this an emergency, react with the ✅ emoji. If this does not qualify as an emergency, react with ❌. \n \n" \
                                            "**Make sure all the details about the incident are clear and you have elaborated clearly on what the issue actually is!** \n \n" \
                                            "__Reminder that the emergency ping is reserved for business production issues that are extremely time sensitive, not for homework or any other non-emergency issue.__ \n \n"
                                            "Approved: {1}/{2} \n \n Denied: {3}/{4}").format(client.emergency_caller_object.author.mention,len(client.approved_list),emergency_request_approval_threshold,len(client.denied_list),emergency_request_deny_threshold))
    await client.bot_emergency_message.add_reaction('✅')
    await client.bot_emergency_message.add_reaction('❌')
    client.bot_emergency_message_link = "https://discord.com/channels/{0.id}/{1}/{2}".format(guild,client.emergency_caller_object.channel.id,client.bot_emergency_message.id)
    emergency_embed = discord.Embed(title="Emergency called",timestamp=datetime.datetime.now(datetime.timezone.utc),color=random.choice(colors))
    emergency_embed.description = "{0.author.mention} ({0.author.id}) used the emergency command in {0.channel.name} (<#{0.channel.id}>))".format(ctx)
    emergency_embed.add_field(name="Link to message",value="{0}".format(client.bot_emergency_message_link))
    await log_channel.send(embed=emergency_embed)
    while client.emergency_active == True:
        await asyncio.sleep(emergency_role_reminder)
        if client.bot_emergency_reminder_count >= emergency_role_timeout:
            await ctx.channel.send("The emergency that was called has been cancelled (timed out). Link to emergency request: {0}".format(client.bot_emergency_message_link))
            cleanup_emergency()
            return
        if client.emergency_active == True:
            client.bot_emergency_reminder_count+=1
            await ctx.channel.send("There is currently an emergency awaiting approval. Link: {0} Please approve/deny it if you can.".format(client.bot_emergency_message_link))
        else:
            return



@client.command(name='clearemergency')
@commands.has_any_role(*moderator_role_IDs)
async def clearemergency(ctx):
    if client.emergency_active == True:
        client.emergency_active = False
        await ctx.channel.send("The current emergency has been cancelled. The emergency command can now be called, assuming it is off cooldown (2 mins).")
    elif client.emergency_active == False:
        await ctx.channel.send("There is currently no active emergency.")


@client.command(name='irc')
@commands.has_any_role(*moderator_role_IDs)
@commands.guild_only()
async def docker_command(ctx, action):
    allowed_actions = ['stop', 'restart', 'start', 'status']
    if action not in allowed_actions:
        await ctx.send("Invalid action. Please use one of: `stop, restart, start`")
        return

    log_channel = client.get_channel(log_channel_ID)

    if action != 'status':

        command = f'docker {action} {irc_relay_container_id}'

        try:
            output = subprocess.check_output(command, shell=True, text=True)
            await ctx.send(f":white_check_mark: {action} successful on the docker container:`{output}`")
        except subprocess.CalledProcessError as e:
            await ctx.send(f"Error executing docker command: {e}")
            return

    elif action == 'status':

        command = f'docker ps -a --filter "id={irc_relay_container_id}"'

        try:
            output = subprocess.check_output(command, shell=True, text=True)
            await ctx.send(f":notepad_spiral: Status of the IRC relay docker container:\n \n`{output}`")
        except subprocess.CalledProcessError as e:
            await ctx.send(f"Error executing docker command: {e}")
            return

    # Create embed message and send it
    irc_reply_embed = discord.Embed(title=f"{action} command used on the IRC relay",timestamp=datetime.datetime.now(datetime.timezone.utc)) 
    irc_reply_embed.color = random.choice(colors)
    irc_reply_embed.description = f"{action} successful on the IRC relay."
    irc_reply_embed.add_field(f"Output of the {action} command:",f"`{output}`")
    irc_reply_embed.set_footer(text="queried by {0}".format(ctx.author.name), icon_url=ctx.author.avatar.url)
    irc_reply_embed.set_author(name=client.user.name, icon_url=client.user.avatar.url)
    await ctx.send(embed=irc_reply_embed)
    await log_channel.send(embed=irc_reply_embed)




client.run(token)
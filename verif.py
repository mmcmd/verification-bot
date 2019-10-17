import logging
import discord
import time
import random
import asyncio
import datetime
from discord.ext import commands
import json

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
prefix = config_json["prefix"]
moderator_role_IDs = config_json["moderator_role_IDs"]
verified_role = int(config_json["verified_role"])
birthday_role_id = int(config_json["birthday_role_ID"])

# Validation of JSON
# Making sure they are ints
colored_roles = [int(c) for c in colored_roles] 
moderator_role_IDs = [int(m) for m in moderator_role_IDs]

# Message Text for verification_requirement_join
verification_requirements_join_text = number_to_days_text(verification_requirement_join)
verification_requirements_message_text = number_to_days_text(verification_requirement_message)

# Discord colors for embedding
colors = [discord.Colour.purple(), discord.Colour.blue(), discord.Colour.red(), discord.Colour.green(), discord.Colour.orange()] 
uptime_start = datetime.datetime.utcnow()

# Logging in to the bot
client = commands.Bot(command_prefix=prefix)


@client.event
async def on_ready():
    print('Logged in as {0.user}'.format(client))
    logging.info('Logged in as {0.user}'.format(client))
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name=status))


# Verification functions
@client.event
async def on_message(message):
    if message.author == client.user: # Ignores the bots own messages
        return

    if message.guild is None:
        logging.info("Direct message received: {0} - sent by {1} (ID: {2})".format(message.content.lower(), message.author.name, message.author.id))
        if "verify" in message.content.lower() or "verified" in message.content.lower():
            # Author's ID
            author_id = int(message.author.id) 

            # Subtracts current time with account creation date to get account age
            account_age = datetime.datetime.utcnow() - message.author.created_at
            
            # Account age in days
            account_age_days = account_age.days 
            
            # Gets the guild
            home_server = client.get_guild(home_server_ID) 
            
            # logs channel
            log_channel = client.get_channel(log_channel_ID) 
            
            # Fetches user info from said guild
            home_server_info = home_server.get_member(author_id) 
            
            # Fetches top role from user info
            home_server_top_role = str(home_server_info.top_role.name) 
            
            # The ID of the role that the bot gives in order for the person to be able to use the server 
            home_server_verified_role = home_server.get_role(verified_role) 

            if home_server_top_role == "@everyone":
                if account_age_days < verification_requirement_message:
                    await message.channel.send("Sorry, your account must be {0} or older in order to get verified. Please either verify with your phone number or contact the mod team through <@{1}}> (Moderator mail, top of the member list) for manual verification if you're unable to verify with a phone number.".format(verification_requirement_message_text, moderator_mail))
                    logembedfail = discord.Embed(description='<@{0}> ({1}) attempted to get manually verified, however his account age is too low ({2} days)'.format(int(author_id), str(author_id), account_age_days),timestamp=datetime.datetime.utcnow(),color=discord.Colour.red())
                    logembedfail.set_author(name=message.author.name, icon_url=message.author.avatar_url)
                    logging.info("{0} ({1}) attempted to get manually verified, but his account age was too low ({2} days)".format(message.author.name, author_id, account_age_days))
                    await log_channel.send(embed=logembedfail)
                    return
                elif account_age_days >= verification_requirement_message:
                    # Adds unverified role to the user
                    await home_server_info.add_roles(home_server_verified_role, reason="User has manually been verified with Verification bot. Account age: {0} days".format(account_age_days))
                    log_embed = discord.Embed(description="<@{0}> has been verified".format(author_id),timestamp=datetime.datetime.utcnow(),color=discord.Colour.green())
                    log_embed.set_author(name=message.author.name, icon_url=message.author.avatar_url)
                    await log_channel.send(embed=log_embed)
                    await message.channel.send("You have been verified. Please remember to read the <#{0}>. You may also assign yourself roles in <#{1}>. If you ever have an issue, do not hesitate to message <@{2}> (Moderator Mail, top of the member list)".format(str(448941767325253632),str(516816975427797012),str(moderator_mail)))
                    await message.add_reaction('✅')
                    logging.info("{0} ({1}) has been verified. Account age: {2} days".format(message.author.name, author_id,account_age_days))
                    return
            else:
                await message.channel.send("You're already able to speak in the server, there is no need for you to get verified. Contact <@{0}> (Moderator Mail, top of the member list) if there is an issue.".format(moderator_mail))
                logging.info("{} ({%d}) attempted to get verified, but doesn't have @ everyone as his top role. Verification aborted.".format(message.author.name,author_id))
                return
    await client.process_commands(message)





# Event to automatically verify people with account ages over N days old
@client.event
async def on_member_join(member):
    member_id = int(member.id)

    # Subtracts current time with account creation date to get account age
    account_age = datetime.datetime.utcnow() - member.created_at 
    
    # Account age in days
    account_age_days = account_age.days 

    # Gets the guild
    home_server = client.get_guild(home_server_ID) 

    # Logs channel
    log_channel = client.get_channel(log_channel_ID) 

    # Fetches user info from said guild
    home_server_info = home_server.get_member(member_id) 

    # The ID of the role that the bot gives in order for the person to be able to use the server 
    home_server_verified_role = home_server.get_role(verified_role) 

    if account_age_days > verification_requirement_join:
        # Adds unverified role to the user
        await home_server_info.add_roles(home_server_verified_role, reason="Account age is over {0} (user account is {1} days old), user has automatically been verified.".format(verification_requirement_join_text, account_age_days)) 
        log_embed = discord.Embed(description="<@{0}> has been verified automatically because his account age is over {1} (user account is {2} days old)".format(member_id, verification_requirement_join_text, account_age_days),timestamp=datetime.datetime.utcnow(),color=discord.Colour.green())
        log_embed.set_author(name=member.id, icon_url=member.avatar_url)
        await log_channel.send(embed=log_embed)
        logging.info("{0} ({1}) has been verified automatically because his account age is over {2} (user account age is {3} days)".format(member.name, member_id, verification_requirement_join_text, account_age_days))
        return
    else:
        return




# Event to remove colored roles when a member unboosts
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
            log_embed_unboost = discord.Embed(description="{0} ({1}) unboosted the server.".format(member.mention,member.id),timestamp=datetime.datetime.utcnow(),color=discord.Colour.red())
            log_embed_unboost.set_author(name=member.name, icon_url=member.avatar_url)
            await log_channel_unboost.send(embed=log_embed_unboost)
            for role in colored_roles:
                role = home_server.get_role(role)
                await updatedmember.remove_roles(role, reason="User unboosted the server, colors have been removed")




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
    birthday_embed = discord.Embed(color=discord.Colour.purple(),timestamp=datetime.datetime.utcnow())
    birthday_embed.set_author(name=birthdayboy.name,icon_url=birthdayboy.avatar_url)
    birthday_embed.set_footer(text="Responsible user: {0}".format(ctx.author.name),icon_url=ctx.author.avatar_url)
    if birthday_role in birthdayboy.roles:
        await birthdayboy.remove_roles(birthday_role,reason="Responsible user: {0}".format(ctx.author.name))
        await ctx.send("<@{0}> removed the Birthday Boy role from <@{1}>".format(ctx.author.id,birthdayboy.id))
        birthday_embed.description = "{0} removed the birthday boy role from {1}".format(ctx.author.name,birthdayboy.name)
        birthday_embed.title = "Birthday boy role removed"
        await log_channel.send(birthday_embed)
    else:
        await birthdayboy.add_roles(birthday_role,reason="Responsible user: {0}".format(ctx.author.name))
        await ctx.send("Gave the birthday boy role to <@{0}>. Automatically removing it in 12 hours.".format(birthdayboy.id))
        birthday_embed.description = "{0} added the birthday boy role to {1}".format(ctx.author.name,birthdayboy.name)
        birthday_embed.title = "Birthday boy role added"
        await log_channel.send(birthday_embed)
        await asyncio.sleep(64800)
        if birthday_role in birthdayboy.roles:
            await birthdayboy.remove_roles(birthday_role,reason="Responsible user: {0}".format(ctx.author.name))
            await ctx.send("Removed the birthday boy role from <@{0}>. <@{1}>".format(birthdayboy.id, ctx.author.id))
            birthday_embed.description = "{0} removed the birthday boy role from {1}".format(ctx.author.name,birthdayboy.name)
            birthday_embed.title = "Birthday boy role removed"
            await log_channel.send(birthday_embed)


@client.command(name='boosters')
@commands.cooldown(1,15,commands.BucketType.channel)
async def boosters(ctx):
    home_server_info = client.get_guild(home_server_ID)
    boosters_list = home_server_info.premium_subscribers
    # Sorts boosters from oldest to most recent
    boosters_list.sort(key=lambda b: b.premium_since) 
    booster_embed = discord.Embed(title="There are currently {0} people boosting the server. Current tier: {1}".format(home_server_info.premium_subscription_count, home_server_info.premium_tier),timestamp=datetime.datetime.utcnow(),color=discord.Colour.blue())
    booster_embed.set_footer(text="queried by {0}".format(ctx.author.name),icon_url=ctx.author.avatar_url)
    booster_embed.set_author(name=ctx.guild.name,icon_url=ctx.guild.icon_url)
    for booster in boosters_list:
        booster_embed.add_field(name="{0}, joined {1}".format(booster.name,booster.joined_at.strftime("%b %d %Y")),value="{0} - Boosting since: {1}".format(booster.mention,booster.premium_since.strftime("%b %d %Y")),inline=False)
    await ctx.send(embed=booster_embed)


@client.command(name='uptime')
@commands.cooldown(1,10,commands.BucketType.user)
async def uptime(ctx):
    uptime_end = datetime.datetime.utcnow() - uptime_start
    uptime_embed = discord.Embed(timestamp=datetime.datetime.utcnow(),color=random.choice(colors))
    uptime_embed.set_author(name=client.user.name, icon_url=client.user.avatar_url)
    uptime_embed.set_footer(text="queried by {0}".format(ctx.author.name),icon_url=ctx.author.avatar_url)
    uptime_embed.add_field(name="Current uptime",value="{0.days} days {1} hours {2} minutes {0.seconds} seconds".format(uptime_end,uptime_end.seconds//3600,(uptime_end.seconds//60)%60)) # Fix seconds
    await ctx.send(embed=uptime_embed)
    logging.info("{0.author.name} ({0.author.id} used uptime command in {0.channel.name} ({0.channel.id}))".format(ctx))
    

@client.command(name='github')
@commands.cooldown(1,10,commands.BucketType.user)
async def github(ctx):
    github_embed = discord.Embed(timestamp=datetime.datetime.utcnow(),colors=random.choice(colors))
    github_embed.set_author(name="github.com/mmcmd",icon_url="https://avatars1.githubusercontent.com/u/36875145")
    github_embed.set_footer(text="queried by {0}".format(ctx.author.name),icon_url=ctx.author.avatar_url)
    github_embed.add_field(name="The source code of this bot can be found at:",value="https://github.com/mmcmd/verification-bot")
    await ctx.send(embed=github_embed)


# Convert Input to Day/Days string
def number_to_days_text(x):
    x_text = "{} day".format(x)
    if(x != 1):
        x_text += "s"


client.run(token)
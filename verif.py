import logging
import discord
import time
import random
import asyncio
import datetime
import discord.ext.commands
import json

client = discord.Client()
logging.basicConfig(filename='verification.log', filemode='w', format='%(name)s - %(levelname)s - %(message)s',level=logging.INFO)
with open("config.json", "r") as read: # Imports config json file
    config_json = json.load(read_file)


## To do: ##

# High priority
# Splitting commands into different functions
# Error handling

# Medium priority
# Command to display last 30 logs

# Low priority
# Advanced logging
# Message when a nitro boost occurs (on_member_update) -> when Nitro booster role is added to someone
# Remove color roles from people who unboost





# Static variables 

token = config_json["token"]
homeserver_id = config_json["homeserver_id"]
moderator_mail = config_json["moderator_mail"]
status = config_json["status"]
log_channel_id = config_json["log_channel_id"]
verified_role = config_json["verified_role"]
colors = [discord.Colour.purple(), discord.Colour.blue(), discord.Colour.red(), discord.Colour.green(), discord.Colour.orange()]



# Bot stuff 

@client.event
async def on_ready():
    print('Logged in as {0.user}'.format(client))
    logging.info('Logged in as {0.user}'.format(client))

    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name=status))



@client.event
async def on_message(message):

    if message.author == client.user: # Ignores the bots own messages
        return

    '''
    if message.content.lower().startswith('$ping'):
        pingem = discord.Embed(color=random.choice(colors))
        pingem.add_field(name=':ping_pong: Ping', value=':ping_pong: Pong')
        pingem.add_field(name=':newspaper: Response time', value=f'{client.latency * 1000:.0f} ms')
        await message.channel.send(embed=pingem)
    '''




    if message.guild is None:
        logging.info("Direct message received: %s - sent by %s (%d)"% (message.content.lower(),message.author.name, message.author.id))
        if "verify" in message.content.lower() or "verified" in message.content.lower():
            author_id = int(message.author.id) # Author's ID
            account_age = datetime.datetime.utcnow() - message.author.created_at # Subtracts current time with account creation date to get account age
            account_age_days = account_age.days # Account age in days
            home_server = client.get_guild(homeserver_id) # Gets the guild
            log_channel = client.get_channel(log_channel_id) # #logs channel
            home_server_info = home_server.get_member(author_id) # Fetches user info from said guild
            home_server_top_role = str(home_server_info.top_role.name) # Fetches top role from user info
            home_server_verified_role = home_server.get_role(verified_role) # The ID of the role that the bot gives in order for the person to be able to use the server 
            if home_server_top_role == "@everyone":
                if account_age_days < 5:
                    await message.channel.send("Sorry, your account must be 5 days or older in order to get verified. Please either verify with your phone number or contact the mod team through <@%s> (Moderator mail, top of the member list) for manual verification if you're unable to verify with a phone number."% str(moderator_mail))
                    logembedfail = discord.Embed(description='<@%d> (%s) attempted to get verified, however his account age is too low (%d days)'% (int(author_id), str(author_id), account_age_days),timestamp=datetime.datetime.utcnow(),color=random.choice(colors))
                    logembedfail.set_author(name=message.author.name, icon_url=message.author.avatar_url)
                    logging.info(message.author.name + "(%d) attempted to get verified, but his account age was too low (%d days)"% (author_id, account_age_days))
                    await log_channel.send(embed=logembedfail)
                    return
                elif account_age_days >= 5:
                    await home_server_info.add_roles(home_server_verified_role, reason="User has verified with Verification bot. Account age: %d" % account_age_days) # Adds unverified role to the user
                    log_embed = discord.Embed(description='<@%d> has been verified'% author_id,timestamp=datetime.datetime.utcnow(),color=random.choice(colors))
                    log_embed.set_author(name=message.author.name, icon_url=message.author.avatar_url)
                    await log_channel.send(embed=log_embed)
                    await message.channel.send("You have been verified. Please remember to read the <#%s>. You may also assign yourself roles in <#%s>. If you ever have an issue, do not hesitate to message <@%s> (Moderator Mail, top of the member list)"% (str(448941767325253632),str(516816975427797012),str(moderator_mail)))
                    await message.add_reaction('✅')
                    logging.info(message.author.name + " (%d) has been verified. Account age: %d days" % (author_id,account_age_days))
                    return
            else:
                await message.channel.send("You're already able to speak in the server, there is no need for you to get verified. Contact <@%s> (Moderator Mail, top of the member list) if there is an issue."% str(moderator_mail))
                logging.info(message.author.name + " (%d) attempted to get verified, but doesn't have @ everyone as his top role. Verification aborted."% author_id)
                return


    '''
    if message.content.lower().startswith("$steve"):
        stevelist = ['<:steve1:418736567373266955>','<:steve2:418736568145149952>', '<:steve3:418736567922851851>', '<:steve4:418736568040292352>','<:steve5:418736568057069569>']
        steves = stevelist[0] + '\n' + stevelist[1] + '\n' + stevelist[2] + '\n' + stevelist[3] + '\n' + stevelist[4]
        steve = discord.Embed(color=random.choice(colors), description=steves)
        await message.channel.send(embed=steve)
    '''

        #discord.ext.commands.cooldown(60,BucketType.default) # Command cooldown https://discordpy.readthedocs.io/en/latest/ext/commands/api.html



# Event to automatically verify people with account ages over 6 months old
@client.event
async def on_member_join(member):
    member_id = int(member.id)
    account_age = datetime.datetime.utcnow() - member.created_at # Subtracts current time with account creation date to get account age
    account_age_days = account_age.days # Account age in days
    home_server = client.get_guild(homeserver_id) # Gets the guild
    log_channel = client.get_channel(log_channel_id) # #logs channel
    home_server_info = home_server.get_member(member_id) # Fetches user info from said guild
    home_server_verified_role = home_server.get_role(verified_role) # The ID of the role that the bot gives in order for the person to be able to use the server 
    if account_age_days > 180:
        await home_server_info.add_roles(home_server_verified_role, reason="Account age is over 3 months (%d days), user has automatically been verified."% account_age_days) # Adds unverified role to the user
        log_embed = discord.Embed(description='<@%d> has been verified automatically because his account age is over 3 months (%d days)'% (member_id,account_age_days),timestamp=datetime.datetime.utcnow(),color=random.choice(colors))
        log_embed.set_author(name=member.id, icon_url=member.avatar_url)
        await log_channel.send(embed=log_embed)
        logging.info('%s (%d) has been verified automatically because his account age is over 3 months (%d days)'% (str(member.author.name),member_id,account_age_days))
        return
    else:
        return










client.run(token)
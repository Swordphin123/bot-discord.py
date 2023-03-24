import math
import uuid

import discord
from discord.ext.commands import Cog
from quart import Quart, make_response, redirect, request

from ..db import db
from ..modules.discord import discordhelper

app = Quart(__name__)
state = str(uuid.uuid4().hex)

# Bot messages are enabled here. Mainly to send Save data edits to discord
@app.route("/", methods=["POST"])
async def index():
    data = await request.get_json()

    if data:
        # Get the message
        topic = data.get("topic", "")
        message = data.get("message", "")

        if topic and message:
            channel = await app.bot.fetch_channel(919686018762956820)
            if channel:
                await channel.send(
                    embed=discord.Embed(
                        title=topic, description=message, colour=0x5387B8
                    )
                )

            return "2"
        else:
            return "1"
    else:
        return "0"


@app.route("/love", methods=["POST", "GET"])
async def verified_role():
    res = await make_response()
    url = discordhelper.get_oauth_url()
    res.set_cookie("clientState", state)
    return redirect(url)


# Route configured in the Discord developer console, the redirect Url to which
# the user is sent after approving the bot for their Discord account. This
# completes a few steps:
# 1. Uses the code to acquire Discord OAuth2 tokens
# 2. Uses the Discord Access Token to fetch the user profile
# 3. Stores the OAuth2 Discord Tokens in Redis / Firestore
# 4. Lets the user know it's all good and to go back to Discord
@app.route("/discord-oauth-callback", methods=["POST", "GET"])
async def discord_oauth_callback():
    # 1. Uses the code to acquire Discord OAuth2 tokens
    code = request.args["code"]
    tokens = discordhelper.get_oauth_tokens(code)

    # 2. Uses the Discord Access Token to fetch the user profile
    me_data = discordhelper.get_user_data(tokens["access_token"])
    user_id = me_data["user"]["id"]

    # Check if the UserId already exists in the database
    exists = db.record("SELECT COUNT(*) FROM oauth WHERE UserId = ?", user_id)

    # Check the result
    if exists[0] > 0:
        # Exists! We can update the table
        db.execute(
            "UPDATE oauth SET Token = ?, Expires = ?, RefreshToken = ?, Scope = ?, TokenType = ? WHERE UserID = ?",
            tokens["access_token"],
            tokens["expires_in"],
            tokens["refresh_token"],
            tokens["scope"],
            tokens["token_type"],
            user_id,
        )
    else:
        # Table does not exist
        db.execute(
            "INSERT INTO oauth (UserId, Token, Expires, RefreshToken, Scope, TokenType) VALUES (?, ?, ?, ?, ?, ?)",
            user_id,
            tokens["access_token"],
            tokens["expires_in"],
            tokens["refresh_token"],
            tokens["scope"],
            tokens["token_type"],
        )

    db.commit()

    # 3. Update the users metadata
    await app.update_metadata(user_id)

    return "You did it! Now go back to Discord."


# This cog is essentially just a helper function to run Quartz
class HttpServices(Cog):
    def __init__(self, bot):
        self.bot = bot

    # Given a Discord UserId, push static make-believe data to the Discord
    # metadata endpoint.
    async def update_metadata(self, user_id):
        print(1)

        # Fetch the Discord tokens from storage
        data = db.record(
            "SELECT Token, Expires, RefreshToken, Scope, TokenType FROM oauth WHERE UserId = ?",
            user_id,
        )

        print(2)

        if data == None:
            return

        print(3)

        # Reconstruct the token data of a user
        token, expires, refresh_token, scope, token_type = data
        tokens = {
            "access_token": token,
            "expires_in": expires,
            "refresh_token": refresh_token,
            "scope": scope,
            "token_type": token_type,
        }
        metadata = {}

        try:
            # Fetch the new metadata you want to use from an external source.
            # This data could be POST-ed to this endpoint, but every service
            # is going to be different.  To keep the example simple, we'll
            # just generate some random data.
            metadata = {
                "hoursplayed": 0,
                "totalenemieskilled": 0,
                "dungeonscompleted": 0,
                "highestcombo": 0,
                "verified": False,
            }

            verification = self.bot.get_cog("Verification")
            member = await self.guild.fetch_member(user_id)
            id = None

            print(member)
            print(4)

            # Determine if this user is verified
            if member:
                print(4.1)
                id = await verification.get_roblox_id(member)
                print(4.2)
                if id:
                    metadata["verified"] = True

            if id == None:
                return

            print(5)

            # Calculate the random stats this user has
            datastore = self.bot.get_cog("Datastore")
            account_json = await datastore.load_data(
                None,
                "Account_ProfileStore_Suffix_7",
                f"{id}_SaveData_Account",
            )

            print(6)

            if type(account_json) == int:
                return

            print(7)

            if account_json == None:
                return

            # Calculate Hours Played
            metadata["hoursplayed"] = math.floor(
                (account_json["Data"]["TotalHours"] / 3600) + 0.5
            )

            # Calculate Total Kills
            for enemyType in ["Mobs", "Bosses"]:
                for enemyKey in account_json["Data"]["Journal"][enemyType]:
                    metadata["totalenemieskilled"] += account_json["Data"]["Journal"][
                        enemyType
                    ][enemyKey]["Kills"]

            # Calculate Dungeons Completed
            metadata["dungeonscompleted"] += account_json["Data"][
                "DungeonNormalCompleted"
            ]
            metadata["dungeonscompleted"] += account_json["Data"][
                "DungeonHeroCompleted"
            ]

            # Calculate the highest combo this user got
            metadata["highestcombo"] = account_json["Data"]["HighestCombo"]

            print(8)

        except Exception as e:
            print("Error fetching external data:" + e)
            # If fetching the profile data for the external service fails for any reason,
            # ensure metadata on the Discord side is nulled out. This prevents cases
            # where the user revokes an external app permissions, and is left with
            # stale linked role data.

        # Push the data to Discord.
        discordhelper.push_metadata(user_id, tokens, metadata)
        print("Updated Metadata")

    @Cog.listener()
    async def on_ready(self):
        if not self.bot.ready:
            self.guild = self.bot.guild
            app.bot = self.bot
            app.update_metadata = self.update_metadata
            self.bot.loop.create_task(app.run_task(host="0.0.0.0", port=5000))
            self.bot.ready_cogs.ready("httpservices")


async def setup(bot):
    await bot.add_cog(HttpServices(bot))

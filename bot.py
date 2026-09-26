import os
import re
import asyncio
import random

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord.ext import commands
from discord.ui import Modal, TextInput

TOKEN = os.environ.get("DISCORD_TOKEN")
print("TOKEN PRESENT :", TOKEN is not None)

# =========================================================
# SALONS
# =========================================================

HISTOIRES_RP_ID = 1541514039677550694
RENDEZ_VOUS_ID = 1541514158225359010
DEMANDES_DOUANES_ID = 1541514241582833866

WL_VALIDEES_ID = 1541541506374967427
WL_REFUSEES_ID = 1541541629687500840

BIENVENUE_ID = 1541513353422315571
DISCUSSION_HRP_ID = 1541382116070264864


# =========================================================
# ROLES
# =========================================================

ROLE_EN_ATTENTE_PAPIER_ID = 1541500475050950799
ROLE_CITOYEN_ID = 1541500931567263744
ROLE_V1_ID = 1541574566231674940


# =========================================================
# DOUANES
# =========================================================

DOUANE_1_ID = 1541499273407893616
DOUANE_2_ID = 1541499414571651163
DOUANE_3_ID = 1541499450197807244


DOUANES = {
    DOUANE_1_ID: "👨‍✈️・Douane 1",
    DOUANE_2_ID: "👨‍✈️・Douane 2",
    DOUANE_3_ID: "👨‍✈️・Douane 3",
}


# =========================================================
# TEMPS
# =========================================================

DUREE_MAX_RESERVATION = timedelta(hours=1)
DUREE_ABSENCE_VOCAL = timedelta(minutes=15)

INTERVALLE_SURVEILLANCE = 10


# =========================================================
# TIMEZONE
# =========================================================

try:
    TIMEZONE = ZoneInfo("Europe/Paris")
except ZoneInfoNotFoundError:
    TIMEZONE = None


def heure_locale():
    if TIMEZONE:
        return datetime.now(TIMEZONE)

    return datetime.now().astimezone()


def rendre_datetime_timezone(dt):

    if dt.tzinfo:
        return dt

    if TIMEZONE:
        return dt.replace(tzinfo=TIMEZONE)

    return dt.astimezone()



# =========================================================
# BOT
# =========================================================

intents = discord.Intents.default()

intents.members = True
intents.message_content = True
intents.voice_states = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents
)



# =========================================================
# VARIABLES
# =========================================================

reservations_douanes = {}

taches_liberation = {}



# =========================================================
# OUTILS
# =========================================================

def recuperer_role(guild, role_id):

    if guild is None:
        return None

    return guild.get_role(role_id)



def recuperer_douane(douane_id):

    return bot.get_channel(douane_id)



def recuperer_serveur_principal():

    salon = bot.get_channel(RENDEZ_VOUS_ID)

    if isinstance(salon, discord.abc.GuildChannel):
        return salon.guild


    for guild in bot.guilds:

        for channel_id in DOUANES:

            if guild.get_channel(channel_id):
                return guild

    return None



async def recuperer_membre(guild, membre_id):

    if guild is None:
        return None


    membre = guild.get_member(membre_id)

    if membre:
        return membre


    try:
        return await guild.fetch_member(membre_id)

    except:
        return None



def recuperer_id_joueur(message):

    if not message or not message.embeds:
        return None


    embed = message.embeds[0]


    for field in embed.fields:

        if field.name.strip() == "👤 Joueur":

            resultat = re.search(
                r"ID\s*:\s*`(\d+)`",
                field.value
            )

            if resultat:
                return int(resultat.group(1))


    return None



# =========================================================
# SYSTEME DOUANES
# =========================================================


def douane_est_reservee(douane_id):

    return douane_id in reservations_douanes



async def trouver_douane_libre():

    for douane_id, nom in DOUANES.items():

        salon = recuperer_douane(douane_id)


        if salon and not douane_est_reservee(douane_id):

            return salon, nom


    return None, None



async def reserver_douane(
    salon,
    joueur,
    date_rdv
):

    if salon.id in reservations_douanes:

        raise RuntimeError(
            "Douane déjà réservée"
        )


    reservations_douanes[salon.id] = {

        "joueur_id": joueur.id,

        "joueur": joueur,

        "date_rdv": date_rdv,

        "date_reservation": heure_locale()

    }


    print(
        f"🚪 Douane réservée {salon.name}"
    )



async def liberer_douane(
    salon,
    raison="Libération"
):

    if salon is None:
        return


    reservations_douanes.pop(
        salon.id,
        None
    )


    tache = taches_liberation.pop(
        salon.id,
        None
    )


    if tache and not tache.done():

        tache.cancel()


    print(
        f"🔓 {salon.name} : {raison}"
    )



async def surveiller_douane(
    salon,
    joueur,
    date_rdv
):

    limite = date_rdv + DUREE_MAX_RESERVATION

    vide_depuis = None


    try:

        while salon.id in reservations_douanes:


            maintenant = heure_locale()



            if maintenant >= limite:

                await liberer_douane(
                    salon,
                    "Temps maximum atteint"
                )

                break



            if len(salon.members) == 0:


                if vide_depuis is None:

                    vide_depuis = maintenant


                elif maintenant - vide_depuis >= DUREE_ABSENCE_VOCAL:


                    await liberer_douane(
                        salon,
                        "Vocal vide 15 minutes"
                    )

                    break


            else:

                vide_depuis = None



            await asyncio.sleep(
                INTERVALLE_SURVEILLANCE
            )


    except asyncio.CancelledError:

        pass
# =========================================================
# PASSEPORT
# =========================================================

class PasseportModal(
    Modal,
    title="🪪 Création passeport RP"
):

    nom = TextInput(
        label="Nom RP",
        max_length=50
    )

    prenom = TextInput(
        label="Prénom RP",
        max_length=50
    )

    age = TextInput(
        label="Âge RP",
        max_length=3
    )

    lore = TextInput(
        label="Histoire RP",
        style=discord.TextStyle.paragraph,
        max_length=2000
    )


    async def on_submit(self, interaction):

        salon = bot.get_channel(
            HISTOIRES_RP_ID
        )


        embed = discord.Embed(
            title="🪪 Nouveau passeport RP",
            color=discord.Color.blue()
        )


        embed.add_field(
            name="👤 Joueur",
            value=(
                f"{interaction.user.mention}\n"
                f"ID : `{interaction.user.id}`"
            ),
            inline=False
        )


        embed.add_field(
            name="Nom RP",
            value=self.nom.value
        )

        embed.add_field(
            name="Prénom RP",
            value=self.prenom.value
        )

        embed.add_field(
            name="Âge RP",
            value=self.age.value
        )


        embed.add_field(
            name="📖 Lore",
            value=self.lore.value,
            inline=False
        )


        await salon.send(
            embed=embed,
            view=DossierStaffView()
        )


        await interaction.response.send_message(
            "✅ Passeport envoyé au staff.",
            ephemeral=True
        )



class PasseportView(discord.ui.View):

    def __init__(self):
        super().__init__(
            timeout=None
        )


    @discord.ui.button(
        label="🪪 Créer mon passeport",
        style=discord.ButtonStyle.primary,
        custom_id="passeport"
    )
    async def passeport(
        self,
        interaction,
        button
    ):

        await interaction.response.send_modal(
            PasseportModal()
        )



# =========================================================
# VALIDATION WL
# =========================================================

class DossierStaffView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )


    @discord.ui.button(
        label="✅ Valider WL",
        style=discord.ButtonStyle.success,
        custom_id="wl_ok"
    )
    async def valider(
        self,
        interaction,
        button
    ):


        if not interaction.user.guild_permissions.administrator:

            await interaction.response.send_message(
                "❌ Staff uniquement",
                ephemeral=True
            )

            return



        joueur_id = recuperer_id_joueur(
            interaction.message
        )


        joueur = await recuperer_membre(
            interaction.guild,
            joueur_id
        )


        citoyen = recuperer_role(
            interaction.guild,
            ROLE_CITOYEN_ID
        )


        v1 = recuperer_role(
            interaction.guild,
            ROLE_V1_ID
        )


        attente = recuperer_role(
            interaction.guild,
            ROLE_EN_ATTENTE_PAPIER_ID
        )


        if attente in joueur.roles:

            await joueur.remove_roles(
                attente
            )


        await joueur.add_roles(
            citoyen,
            v1
        )



        # Libération douane automatique

        for did, data in list(
            reservations_douanes.items()
        ):

            if data["joueur_id"] == joueur.id:

                await liberer_douane(
                    recuperer_douane(did),
                    "WL validée"
                )



        try:

            await joueur.send(
                "🎉 Ta WL LifeWorld est validée !"
            )

        except:

            pass



        await interaction.response.send_message(
            "✅ WL validée",
            ephemeral=True
        )



# =========================================================
# RENDEZ VOUS
# =========================================================


class RendezVousView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )


    @discord.ui.button(
        label="✅ Valider rendez-vous",
        style=discord.ButtonStyle.success,
        custom_id="rdv_ok"
    )
    async def valider_rdv(
        self,
        interaction,
        button
    ):


        joueur = interaction.user


        douane, nom = await trouver_douane_libre()


        if not douane:

            await interaction.response.send_message(
                "❌ Toutes les douanes sont occupées.",
                ephemeral=True
            )

            return



        await reserver_douane(
            douane,
            joueur,
            heure_locale()
        )


        await interaction.response.send_message(
            f"✅ Rendez-vous confirmé\n"
            f"🚪 Va dans {nom}\n\n"
            "La douane n'est pas renommée.\n"
            "Tu dois te placer toi-même dans le vocal.",
            ephemeral=True
        )


        tache = asyncio.create_task(
            surveiller_douane(
                douane,
                joueur,
                heure_locale()
            )
        )


        taches_liberation[douane.id] = tache



# =========================================================
# BIENVENUE
# =========================================================

async def envoyer_message_passeport(member):

    try:

        await member.send(
            "👋 Bienvenue sur LifeWorld !\n\n"
            "Crée ton passeport RP.",
            view=PasseportView()
        )

        return True


    except:

        return False



@bot.event
async def on_member_join(member):

    role = member.guild.get_role(
        ROLE_EN_ATTENTE_PAPIER_ID
    )


    if role:

        await member.add_roles(
            role
        )


    await envoyer_message_passeport(
        member
    )


    salon = bot.get_channel(
        BIENVENUE_ID
    )


    if salon:

        await salon.send(
            f"👋 Bienvenue {member.mention} sur LifeWorld !"
        )



# =========================================================
# READY
# =========================================================


@bot.event
async def on_ready():

    bot.add_view(
        PasseportView()
    )

    bot.add_view(
        DossierStaffView()
    )

    bot.add_view(
        RendezVousView()
    )


    await bot.tree.sync()


    print(
        f"✅ Connecté : {bot.user}"
    )



# =========================================================
# LANCEMENT
# =========================================================

if not TOKEN:

    print(
        "❌ DISCORD_TOKEN absent"
    )

else:

    bot.run(
        TOKEN
    )
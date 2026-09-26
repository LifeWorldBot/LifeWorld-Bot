import os
import re
import asyncio
import random

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord.ext import commands
from discord.ui import Modal, TextInput
from dotenv import load_dotenv


# =========================================================
# CONFIGURATION
# =========================================================


TOKEN = os.getenv("DISCORD_TOKEN")


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
# TEMPS DES DOUANES
# =========================================================

DUREE_MAX_RESERVATION = timedelta(hours=1)
DUREE_ABSENCE_VOCAL = timedelta(minutes=15)
INTERVALLE_SURVEILLANCE = 10


# =========================================================
# FUSEAU HORAIRE
# =========================================================

try:
    TIMEZONE = ZoneInfo("Europe/Paris")
except ZoneInfoNotFoundError:
    print("⚠️ tzdata absent : utilisation de l'heure locale du PC.")
    TIMEZONE = None


def heure_locale():
    return datetime.now(TIMEZONE) if TIMEZONE else datetime.now().astimezone()


def rendre_datetime_timezone(dt):
    if dt.tzinfo is not None:
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
    intents=intents,
)


# =========================================================
# RESERVATIONS DOUANES
# =========================================================

reservations_douanes = {}

taches_liberation = {}


# =========================================================
# OUTILS
# =========================================================

def recuperer_id_joueur(message):
    if message is None or not message.embeds:
        return None

    embed = message.embeds[0]

    for field in embed.fields:
        if field.name.strip() == "👤 Joueur":
            resultat = re.search(
                r"ID\s*:\s*`(\d+)`",
                field.value,
            )

            if resultat:
                return int(resultat.group(1))

    return None


def recuperer_date_rdv(message):
    if message is None:
        return None

    date_str = None
    heure_str = None

    if message.embeds:
        embed = message.embeds[0]

        for field in embed.fields:
            nom = field.name.strip()
            valeur = field.value.strip()

            if nom == "📅 Date":
                date_str = valeur

            elif nom == "🕐 Heure":
                heure_str = valeur

    contenu = message.content or ""

    if not date_str:
        match = re.search(
            r"📅\s*(?:\*\*)?Date(?:\*\*)?\s*:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})",
            contenu,
            re.IGNORECASE,
        )

        if match:
            date_str = match.group(1)

    if not heure_str:
        match = re.search(
            r"🕐\s*(?:\*\*)?Heure(?:\*\*)?\s*:\s*([0-9]{1,2}:[0-9]{2})",
            contenu,
            re.IGNORECASE,
        )

        if match:
            heure_str = match.group(1)

    if not date_str:
        match = re.search(
            r"\b([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})\b",
            contenu,
        )

        if match:
            date_str = match.group(1)

    if not heure_str:
        match = re.search(
            r"\b([0-9]{1,2}:[0-9]{2})\b",
            contenu,
        )

        if match:
            heure_str = match.group(1)

    if not date_str or not heure_str:
        print("❌ Impossible de récupérer date/heure du rendez-vous.")
        return None

    try:
        dt = datetime.strptime(
            f"{date_str} {heure_str}",
            "%d/%m/%Y %H:%M",
        )

        return rendre_datetime_timezone(dt)

    except ValueError as erreur:
        print(f"❌ Erreur conversion date : {erreur}")
        return None


def recuperer_role(guild, role_id):
    if guild is None:
        return None

    return guild.get_role(role_id)


def recuperer_serveur_principal():
    salon = bot.get_channel(RENDEZ_VOUS_ID)

    if isinstance(salon, discord.abc.GuildChannel):
        return salon.guild

    salon = bot.get_channel(HISTOIRES_RP_ID)

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

    except discord.NotFound:
        return None

    except discord.HTTPException as erreur:
        print(f"❌ Erreur récupération membre : {erreur}")
        return None


async def recuperer_membre_depuis_mp(user_id):
    guild = recuperer_serveur_principal()

    if guild is None:
        return None, None

    membre = await recuperer_membre(
        guild,
        user_id,
    )

    return guild, membre


# =========================================================
# GESTION DES DOUANES
# =========================================================

def douane_est_reservee(douane_id):
    return douane_id in reservations_douanes


def recuperer_douane(douane_id):
    return bot.get_channel(douane_id)


async def trouver_douane_libre():
    """
    Cherche une douane disponible.

    IMPORTANT :
    - Le nom de la douane n'est jamais modifié.
    - Aucune douane ne devient nominative.
    - Le joueur doit lui-même se placer dans
      une douane disponible.
    """

    for douane_id, nom_original in DOUANES.items():

        salon = recuperer_douane(douane_id)

        if salon is None:
            continue

        if not douane_est_reservee(douane_id):
            return salon, nom_original

    return None, None


async def reserver_douane(
    salon,
    joueur,
    date_rdv,
):
    """
    Réserve une douane sans modifier son nom.
    """

    if salon is None or joueur is None:
        raise ValueError("Salon ou joueur invalide.")

    if salon.id in reservations_douanes:
        raise RuntimeError("Cette douane est déjà réservée.")

    reservations_douanes[salon.id] = {
        "joueur_id": joueur.id,
        "joueur": joueur,
        "date_rdv": date_rdv,
        "reservee_le": heure_locale(),
    }

    print(
        f"🚪 Douane réservée : {salon.name} pour {joueur}"
    )

    return True


async def liberer_douane(
    salon,
    raison="Douane libérée",
):
    """
    Libère une douane.

    Aucun renommage.
    Aucune permission nominative.
    """

    if salon is None:
        return

    douane_id = salon.id

    reservations_douanes.pop(
        douane_id,
        None,
    )

    tache = taches_liberation.pop(
        douane_id,
        None,
    )

    if (
        tache
        and not tache.done()
        and tache != asyncio.current_task()
    ):
        tache.cancel()

    print(
        f"🔓 {salon.name} libérée : {raison}"
    )


# =========================================================
# SURVEILLANCE DOUANE
# =========================================================

async def surveiller_douane(
    salon,
    joueur,
    date_rdv,
):
    """
    Surveillance de la douane.

    - Le nom de la douane ne change jamais.
    - Le joueur se place lui-même dans le vocal.
    - Si le vocal reste vide 15 minutes : libération.
    - Après 1 heure maximum : libération.
    """

    douane_id = salon.id

    heure_limite = (
        date_rdv + DUREE_MAX_RESERVATION
    )

    vocal_vide_depuis = None

    try:

        print(
            f"👀 Surveillance activée : {salon.name}"
        )

        while True:

            maintenant = heure_locale()

            if douane_id not in reservations_douanes:
                break

            # =================================================
            # LIMITE D'UNE HEURE
            # =================================================

            if maintenant >= heure_limite:

                print(
                    f"⏰ 1 heure atteinte pour {salon.name}."
                )

                await liberer_douane(
                    salon,
                    "Délai maximum d'une heure atteint",
                )

                try:
                    await joueur.send(
                        "🔓 **Douane libérée**\n\n"
                        f"Ta réservation dans **{salon.name}** "
                        "a été libérée automatiquement car "
                        "le délai maximum d'une heure est terminé."
                    )
                except discord.HTTPException:
                    pass

                break

            # =================================================
            # MEMBRES DANS LE VOCAL
            # =================================================

            membres_vocaux = list(
                salon.members
            )

            vocal_vide = (
                len(membres_vocaux) == 0
            )

            if vocal_vide:

                if vocal_vide_depuis is None:

                    vocal_vide_depuis = maintenant

                    print(
                        f"🔎 {salon.name} est vide. "
                        "Début du compteur de 15 minutes."
                    )

                else:

                    duree_vide = (
                        maintenant
                        - vocal_vide_depuis
                    )

                    if (
                        duree_vide
                        >= DUREE_ABSENCE_VOCAL
                    ):

                        print(
                            f"🔓 {salon.name} vide depuis 15 minutes."
                        )

                        await liberer_douane(
                            salon,
                            "Vocal vide pendant 15 minutes",
                        )

                        try:
                            await joueur.send(
                                "🔓 **Douane libérée**\n\n"
                                f"**{salon.name}** a été libérée "
                                "automatiquement car le vocal "
                                "était vide pendant **15 minutes**."
                            )
                        except discord.HTTPException:
                            pass

                        break

            else:

                if vocal_vide_depuis is not None:

                    print(
                        f"🎙️ Quelqu'un est revenu dans "
                        f"{salon.name}. "
                        "Compteur de 15 minutes annulé."
                    )

                vocal_vide_depuis = None

            await asyncio.sleep(
                INTERVALLE_SURVEILLANCE
            )

    except asyncio.CancelledError:

        print(
            f"⚠️ Surveillance annulée : {salon.name}"
        )

        raise

    except Exception as erreur:

        print(
            f"❌ Erreur surveillance "
            f"{salon.name} : {erreur}"
        )

    finally:

        if douane_id in taches_liberation:
            taches_liberation.pop(
                douane_id,
                None,
            )


# =========================================================
# PASSEPORT
# =========================================================

class PasseportModal(
    Modal,
    title="🪪 Création de ton passeport RP",
):

    nom = TextInput(
        label="Nom RP",
        placeholder="Exemple : Dupont",
        max_length=50,
        required=True,
    )

    prenom = TextInput(
        label="Prénom RP",
        placeholder="Exemple : Jean",
        max_length=50,
        required=True,
    )

    age = TextInput(
        label="Âge RP",
        placeholder="Exemple : 25",
        max_length=3,
        required=True,
    )

    lore = TextInput(
        label="Histoire / Lore",
        placeholder="Raconte l'histoire de ton personnage...",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=True,
    )

    async def on_submit(self, interaction):

        salon = bot.get_channel(
            HISTOIRES_RP_ID
        )

        if salon is None:

            await interaction.response.send_message(
                "❌ Le salon des histoires RP est introuvable.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🪪 Nouveau passeport RP",
            description=(
                "Un joueur vient de remplir son passeport.\n"
                "Le dossier est maintenant en attente de traitement par le staff."
            ),
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="👤 Joueur",
            value=(
                f"{interaction.user.mention}\n"
                f"ID : `{interaction.user.id}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Nom RP",
            value=self.nom.value,
            inline=True,
        )

        embed.add_field(
            name="Prénom RP",
            value=self.prenom.value,
            inline=True,
        )

        embed.add_field(
            name="Âge RP",
            value=self.age.value,
            inline=True,
        )

        embed.add_field(
            name="📖 Histoire / Lore",
            value=self.lore.value,
            inline=False,
        )

        embed.set_footer(
            text="⏳ En attente de traitement"
        )

        try:

            await salon.send(
                embed=embed,
                view=DossierStaffView(),
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                "❌ Je n'ai pas la permission d'envoyer le dossier.",
                ephemeral=True,
            )
            return

        except discord.HTTPException as erreur:

            print(
                f"❌ Erreur envoi dossier : {erreur}"
            )

            await interaction.response.send_message(
                "❌ Une erreur est survenue lors de l'envoi du dossier.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "✅ Ton passeport a bien été envoyé au staff !\n\n"
            "Ton dossier est maintenant en attente de traitement.",
            ephemeral=True,
        )


class PasseportView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🪪 Créer mon passeport",
        style=discord.ButtonStyle.primary,
        custom_id="creer_passeport",
    )
    async def creer_passeport(
        self,
        interaction,
        button,
    ):

        await interaction.response.send_modal(
            PasseportModal()
        )


# =========================================================
# DOSSIER STAFF
# =========================================================

class DossierStaffView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📅 Proposer un rendez-vous",
        style=discord.ButtonStyle.primary,
        custom_id="proposer_rendez_vous",
    )
    async def proposer_rendez_vous(
        self,
        interaction,
        button,
    ):

        if (
            not interaction.guild
            or not interaction.user.guild_permissions.administrator
        ):

            await interaction.response.send_message(
                "❌ Cette action est réservée au staff.",
                ephemeral=True,
            )
            return

        joueur_id = recuperer_id_joueur(
            interaction.message
        )

        if joueur_id is None:

            await interaction.response.send_message(
                "❌ Impossible de retrouver le joueur.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            RendezVousModal(joueur_id)
        )

    @discord.ui.button(
        label="✅ Valider la WL",
        style=discord.ButtonStyle.success,
        custom_id="valider_wl",
    )
    async def valider_wl(
        self,
        interaction,
        button,
    ):

        if (
            not interaction.guild
            or not interaction.user.guild_permissions.administrator
        ):

            await interaction.response.send_message(
                "❌ Cette action est réservée au staff.",
                ephemeral=True,
            )
            return

        joueur_id = recuperer_id_joueur(
            interaction.message
        )

        if joueur_id is None:

            await interaction.response.send_message(
                "❌ Impossible de retrouver le joueur.",
                ephemeral=True,
            )
            return

        guild = interaction.guild

        joueur = await recuperer_membre(
            guild,
            joueur_id,
        )

        if joueur is None:

            await interaction.response.send_message(
                "❌ Impossible de retrouver le membre sur le serveur.",
                ephemeral=True,
            )
            return

        role_attente = recuperer_role(
            guild,
            ROLE_EN_ATTENTE_PAPIER_ID,
        )

        role_citoyen = recuperer_role(
            guild,
            ROLE_CITOYEN_ID,
        )

        role_v1 = recuperer_role(
            guild,
            ROLE_V1_ID,
        )

        if role_citoyen is None:

            await interaction.response.send_message(
                "❌ Le rôle **Citoyen** est introuvable.",
                ephemeral=True,
            )
            return

        if role_v1 is None:

            await interaction.response.send_message(
                "❌ Le rôle **V1** est introuvable.",
                ephemeral=True,
            )
            return

        try:

            if (
                role_attente
                and role_attente in joueur.roles
            ):

                await joueur.remove_roles(
                    role_attente,
                    reason="WL validée",
                )

            if role_citoyen not in joueur.roles:

                await joueur.add_roles(
                    role_citoyen,
                    reason="WL validée",
                )

            if role_v1 not in joueur.roles:

                await joueur.add_roles(
                    role_v1,
                    reason="WL validée",
                )

        except discord.Forbidden:

            await interaction.response.send_message(
                "❌ Je n'ai pas les permissions nécessaires pour modifier les rôles.",
                ephemeral=True,
            )
            return

        except discord.HTTPException as erreur:

            print(
                f"❌ Erreur rôles : {erreur}"
            )

            await interaction.response.send_message(
                "❌ Erreur pendant la modification des rôles.",
                ephemeral=True,
            )
            return

        # =================================================
        # LIBERATION DOUANE DU JOUEUR
        # =================================================

        reservation_a_supprimer = None

        for douane_id, reservation in list(
            reservations_douanes.items()
        ):

            if reservation["joueur_id"] == joueur.id:

                reservation_a_supprimer = douane_id
                break

        if reservation_a_supprimer:

            douane = recuperer_douane(
                reservation_a_supprimer
            )

            if douane:

                await liberer_douane(
                    douane,
                    "WL du joueur validée",
                )

        # =================================================
        # SORTIE DE DOUANE
        # =================================================

        if joueur.voice and joueur.voice.channel:

            if joueur.voice.channel.id in DOUANES:

                try:

                    await joueur.move_to(
                        None,
                        reason="WL validée - sortie de la douane",
                    )

                    print(
                        f"🚪 {joueur} retiré de la douane "
                        "après validation WL."
                    )

                except discord.Forbidden:

                    print(
                        "⚠️ Impossible de déplacer le joueur."
                    )

                except discord.HTTPException as erreur:

                    print(
                        f"⚠️ Erreur déplacement joueur : {erreur}"
                    )

        # =================================================
        # ARCHIVE WL VALIDEE
        # =================================================

        salon_valide = bot.get_channel(
            WL_VALIDEES_ID
        )

        if salon_valide:

            embed_valide = discord.Embed(
                title="✅ WL VALIDÉE",
                description="Le dossier de ce joueur a été validé.",
                color=discord.Color.green(),
            )

            if interaction.message.embeds:

                for field in interaction.message.embeds[0].fields:

                    embed_valide.add_field(
                        name=field.name,
                        value=field.value,
                        inline=field.inline,
                    )

            embed_valide.set_footer(
                text=f"Validée par {interaction.user.display_name}"
            )

            try:

                await salon_valide.send(
                    embed=embed_valide
                )

            except discord.HTTPException as erreur:

                print(
                    f"❌ Erreur archive WL validée : {erreur}"
                )

        # =================================================
        # MESSAGE DISCUSSION HRP
        # =================================================

        salon_hrp = bot.get_channel(
            DISCUSSION_HRP_ID
        )

        if salon_hrp:

            try:

                await salon_hrp.send(
                    "🎉 **Un nouveau arrive en ville !**\n\n"
                    f"Souhaitez la bienvenue à {joueur.mention} ! 👋\n"
                    "Allez lui dire bonjour et soyez sympa avec lui… "
                    "enfin, essayez de ne pas lui faire peur dès son arrivée. 😄"
                )

            except discord.HTTPException as erreur:

                print(
                    f"❌ Erreur message HRP : {erreur}"
                )

        # =================================================
        # MP JOUEUR
        # =================================================

        try:

            await joueur.send(
                "🎉 **Félicitations !**\n\n"
                "Ta WL sur **LifeWorld** vient d'être validée !\n\n"
                "Tu possèdes maintenant les rôles "
                "**Citoyen** et **V1**.\n\n"
                "Ton passage par la douane est terminé.\n"
                "Tu peux maintenant rejoindre les salons classiques "
                "du serveur.\n\n"
                "Bienvenue dans la ville ! 🏙️"
            )

        except discord.Forbidden:

            print(
                f"⚠️ Impossible d'envoyer un MP à {joueur}."
            )

        except discord.HTTPException as erreur:

            print(
                f"❌ Erreur MP validation : {erreur}"
            )

        # =================================================
        # DESACTIVER BOUTONS
        # =================================================

        for item in self.children:
            item.disabled = True

        try:

            await interaction.message.edit(
                view=self
            )

        except discord.HTTPException:
            pass

        await interaction.response.send_message(
            "✅ **WL validée !**\n\n"
            f"{joueur.mention} possède maintenant "
            "**Citoyen** et **V1**.\n\n"
            "🚪 S'il était dans une douane, celle-ci a été libérée.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="❌ Refuser la WL",
        style=discord.ButtonStyle.danger,
        custom_id="refuser_wl",
    )
    async def refuser_wl(
        self,
        interaction,
        button,
    ):

        if (
            not interaction.guild
            or not interaction.user.guild_permissions.administrator
        ):

            await interaction.response.send_message(
                "❌ Cette action est réservée au staff.",
                ephemeral=True,
            )
            return

        joueur_id = recuperer_id_joueur(
            interaction.message
        )

        if joueur_id is None:

            await interaction.response.send_message(
                "❌ Impossible de retrouver le joueur.",
                ephemeral=True,
            )
            return

        salon_refuse = bot.get_channel(
            WL_REFUSEES_ID
        )

        if salon_refuse:

            embed_refuse = discord.Embed(
                title="❌ WL REFUSÉE",
                description="Le dossier de ce joueur a été refusé.",
                color=discord.Color.red(),
            )

            if interaction.message.embeds:

                for field in interaction.message.embeds[0].fields:

                    embed_refuse.add_field(
                        name=field.name,
                        value=field.value,
                        inline=field.inline,
                    )

            embed_refuse.set_footer(
                text=f"Refusée par {interaction.user.display_name}"
            )

            try:

                await salon_refuse.send(
                    embed=embed_refuse
                )

            except discord.HTTPException as erreur:

                print(
                    f"❌ Erreur archive WL refusée : {erreur}"
                )

        try:

            joueur = await bot.fetch_user(
                joueur_id
            )

            await joueur.send(
                "❌ **Ta WL LifeWorld a été refusée.**\n\n"
                "Le staff a traité ton dossier.\n"
                "Tu peux contacter le staff pour connaître la suite."
            )

        except (
            discord.NotFound,
            discord.Forbidden,
        ):
            pass

        except discord.HTTPException as erreur:

            print(
                f"❌ Erreur MP refus : {erreur}"
            )

        for item in self.children:
            item.disabled = True

        try:

            await interaction.message.edit(
                view=self
            )

        except discord.HTTPException:
            pass

        await interaction.response.send_message(
            "❌ **WL refusée.**\n\n"
            "Le dossier a été envoyé dans le salon des WL refusées.",
            ephemeral=True,
        )


# =========================================================
# MODAL RENDEZ-VOUS
# =========================================================

class RendezVousModal(Modal):

    def __init__(self, joueur_id):

        super().__init__(
            title="📅 Proposer un rendez-vous"
        )

        self.joueur_id = joueur_id

        self.date = TextInput(
            label="Date",
            placeholder="Exemple : 28/09/2026",
            max_length=10,
            required=True,
        )

        self.heure = TextInput(
            label="Heure",
            placeholder="Exemple : 21:00",
            max_length=5,
            required=True,
        )

        self.information = TextInput(
            label="Information supplémentaire",
            placeholder="Exemple : Rendez-vous au bureau des douanes.",
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=False,
        )

        self.add_item(self.date)
        self.add_item(self.heure)
        self.add_item(self.information)

    async def on_submit(self, interaction):

        salon = bot.get_channel(
            RENDEZ_VOUS_ID
        )

        if salon is None:

            await interaction.response.send_message(
                "❌ Le salon rendez-vous est introuvable.",
                ephemeral=True,
            )
            return

        date_input = self.date.value.strip()
        heure_input = self.heure.value.strip()

        try:

            date_rdv = datetime.strptime(
                f"{date_input} {heure_input}",
                "%d/%m/%Y %H:%M",
            )

            date_rdv = rendre_datetime_timezone(
                date_rdv
            )

        except ValueError:

            await interaction.response.send_message(
                "❌ Date ou heure invalide.\n\n"
                "Utilise exactement :\n"
                "📅 Date : `28/09/2026`\n"
                "🕐 Heure : `21:00`",
                ephemeral=True,
            )
            return

        if date_rdv <= heure_locale():

            await interaction.response.send_message(
                "❌ Tu ne peux pas proposer un rendez-vous dans le passé.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="📅 Nouveau rendez-vous proposé",
            description=(
                "Un rendez-vous a été proposé pour ton dossier RP."
            ),
            color=discord.Color.orange(),
        )

        embed.add_field(
            name="👤 Joueur",
            value=f"<@{self.joueur_id}>",
            inline=False,
        )

        embed.add_field(
            name="📅 Date",
            value=date_rdv.strftime("%d/%m/%Y"),
            inline=True,
        )

        embed.add_field(
            name="🕐 Heure",
            value=date_rdv.strftime("%H:%M"),
            inline=True,
        )

        if self.information.value:

            embed.add_field(
                name="📋 Information",
                value=self.information.value,
                inline=False,
            )

        embed.set_footer(
            text="⏳ Rendez-vous envoyé au joueur"
        )

        try:

            await salon.send(
                embed=embed
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                "❌ Je n'ai pas la permission d'écrire dans le salon rendez-vous.",
                ephemeral=True,
            )
            return

        except discord.HTTPException as erreur:

            print(
                f"❌ Erreur rendez-vous : {erreur}"
            )

            await interaction.response.send_message(
                "❌ Impossible d'envoyer le rendez-vous.",
                ephemeral=True,
            )
            return

        try:

            joueur = await bot.fetch_user(
                self.joueur_id
            )

        except discord.NotFound:

            await interaction.response.send_message(
                "⚠️ Rendez-vous créé, mais joueur introuvable.",
                ephemeral=True,
            )
            return

        except discord.HTTPException as erreur:

            print(
                f"❌ Erreur récupération joueur : {erreur}"
            )

            await interaction.response.send_message(
                "⚠️ Rendez-vous créé, mais impossible de contacter le joueur.",
                ephemeral=True,
            )
            return

        message_mp = (
            "📅 **Rendez-vous LifeWorld**\n\n"
            "Le staff te propose le rendez-vous suivant :\n\n"
            f"📅 **Date :** {date_rdv.strftime('%d/%m/%Y')}\n"
            f"🕐 **Heure :** {date_rdv.strftime('%H:%M')}\n\n"
        )

        if self.information.value:

            message_mp += (
                f"📋 **Information :** "
                f"{self.information.value}\n\n"
            )

        message_mp += (
            "Clique sur **Valider le rendez-vous** lorsque tu es prêt."
        )

        try:

            await joueur.send(
                message_mp,
                view=RendezVousView(),
            )

            await interaction.response.send_message(
                "✅ Le rendez-vous a été envoyé au joueur en MP.",
                ephemeral=True,
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                "⚠️ Rendez-vous créé, mais je ne peux pas envoyer de MP au joueur.",
                ephemeral=True,
            )

        except discord.HTTPException as erreur:

            print(
                f"❌ Erreur envoi MP : {erreur}"
            )

            await interaction.response.send_message(
                "⚠️ Rendez-vous créé, mais le MP n'a pas pu être envoyé.",
                ephemeral=True,
            )


# =========================================================
# RENDEZ-VOUS VIEW
# =========================================================

class RendezVousView(discord.ui.View):

    def __init__(self):
        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="✅ Valider le rendez-vous",
        style=discord.ButtonStyle.success,
        custom_id="valider_rendez_vous",
    )
    async def valider_rendez_vous(
        self,
        interaction,
        button,
    ):

        date_rdv = recuperer_date_rdv(
            interaction.message
        )

        if date_rdv is None:

            await interaction.response.send_message(
                "❌ Impossible de récupérer la date du rendez-vous.",
                ephemeral=True,
            )
            return

        if date_rdv <= heure_locale():

            await interaction.response.send_message(
                "❌ Ce rendez-vous est déjà passé.",
                ephemeral=True,
            )
            return

        if interaction.guild is None:

            guild, joueur = (
                await recuperer_membre_depuis_mp(
                    interaction.user.id
                )
            )

        else:

            guild = interaction.guild

            joueur = await recuperer_membre(
                guild,
                interaction.user.id,
            )

        if guild is None:

            await interaction.response.send_message(
                "❌ Impossible de retrouver le serveur LifeWorld.",
                ephemeral=True,
            )
            return

        if joueur is None:

            await interaction.response.send_message(
                "❌ Impossible de retrouver ton compte sur LifeWorld.",
                ephemeral=True,
            )
            return

        # =================================================
        # VERIFIER DOUANE EXISTANTE
        # =================================================

        for douane_id, reservation in reservations_douanes.items():

            if reservation["joueur_id"] == joueur.id:

                douane_existante = recuperer_douane(
                    douane_id
                )

                if douane_existante:

                    await interaction.response.send_message(
                        "⚠️ Tu as déjà une douane réservée : "
                        f"**{douane_existante.name}**.\n\n"
                        "Place-toi dans ce vocal.",
                        ephemeral=True,
                    )

                    return

        # =================================================
        # TROUVER UNE DOUANE LIBRE
        # =================================================

        douane, nom_douane = (
            await trouver_douane_libre()
        )

        if douane is None:

            await interaction.response.send_message(
                "❌ **Aucune douane n'est disponible actuellement.**\n\n"
                "Les trois douanes sont déjà réservées.\n\n"
                "Attends qu'une douane soit libérée.",
                ephemeral=True,
            )
            return

        # =================================================
        # RESERVER LA DOUANE
        # =================================================

        try:

            await reserver_douane(
                douane,
                joueur,
                date_rdv,
            )

        except RuntimeError:

            await interaction.response.send_message(
                "❌ Cette douane vient d'être réservée. Réessaie.",
                ephemeral=True,
            )
            return

        except Exception as erreur:

            print(
                f"❌ Erreur réservation : {erreur}"
            )

            await interaction.response.send_message(
                "❌ Une erreur est survenue pendant la réservation.",
                ephemeral=True,
            )
            return

        # =================================================
        # MESSAGE JOUEUR
        # =================================================

        await interaction.response.send_message(
            "✅ **Rendez-vous confirmé !**\n\n"
            f"🚪 **Ta douane disponible : {nom_douane}**\n\n"
            "➡️ Lorsque tu arrives, **place-toi toi-même "
            "dans cette douane**.\n\n"
            "⚠️ Le bot **ne renomme pas la douane**.\n"
            "⚠️ Le bot **ne rend pas la douane nominative**.\n"
            "⚠️ Le bot **ne te déplace pas automatiquement**.\n\n"
            "🎙️ Si le vocal reste complètement vide pendant "
            "**15 minutes**, la réservation sera libérée.\n\n"
            "⏰ La réservation sera également automatiquement "
            "libérée au maximum **1 heure après le rendez-vous**.",
            ephemeral=True,
        )

        # =================================================
        # MESSAGE STAFF
        # =================================================

        salon_rdv = bot.get_channel(
            RENDEZ_VOUS_ID
        )

        if salon_rdv:

            try:

                await salon_rdv.send(
                    f"✅ {joueur.mention} a validé son rendez-vous.\n\n"
                    f"🚪 Douane disponible : **{nom_douane}**\n"
                    f"📅 {date_rdv.strftime('%d/%m/%Y')}\n"
                    f"🕐 {date_rdv.strftime('%H:%M')}\n\n"
                    "🎙️ Le joueur doit se placer lui-même "
                    "dans le vocal.\n"
                    "🚫 La douane n'est pas nominative.\n"
                    "⏱️ Libération automatique après 15 minutes "
                    "sans personne dans le vocal."
                )

            except discord.HTTPException as erreur:

                print(
                    f"❌ Erreur message staff : {erreur}"
                )

        # =================================================
        # DESACTIVER BOUTONS
        # =================================================

        for item in self.children:
            item.disabled = True

        try:

            await interaction.message.edit(
                view=self
            )

        except discord.HTTPException:
            pass

        # =================================================
        # LANCER SURVEILLANCE
        # =================================================

        ancienne_tache = taches_liberation.get(
            douane.id
        )

        if (
            ancienne_tache
            and not ancienne_tache.done()
        ):
            ancienne_tache.cancel()

        tache = asyncio.create_task(
            surveiller_douane(
                douane,
                joueur,
                date_rdv,
            )
        )

        taches_liberation[
            douane.id
        ] = tache

    @discord.ui.button(
        label="🔄 Demander un autre créneau",
        style=discord.ButtonStyle.secondary,
        custom_id="autre_creneau",
    )
    async def autre_creneau(
        self,
        interaction,
        button,
    ):

        salon = bot.get_channel(
            RENDEZ_VOUS_ID
        )

        if salon:

            try:

                await salon.send(
                    f"🔄 {interaction.user.mention} "
                    "demande **un autre créneau**."
                )

            except discord.HTTPException as erreur:

                print(
                    f"❌ Erreur demande autre créneau : {erreur}"
                )

        await interaction.response.send_message(
            "🔄 **Demande envoyée !**\n\n"
            "Le staff a été informé.",
            ephemeral=True,
        )

        for item in self.children:
            item.disabled = True

        try:

            await interaction.message.edit(
                view=self
            )

        except discord.HTTPException:
            pass


# =========================================================
# PASSEPORT / MESSAGE BIENVENUE
# =========================================================

async def envoyer_message_passeport(member):

    message = (
        "👋 **Bienvenue sur LifeWorld !**\n\n"
        "Avant de commencer ton aventure RP, "
        "tu dois créer ton passeport.\n\n"
        "Clique sur le bouton ci-dessous pour remplir ton "
        "nom RP, prénom RP, âge et histoire.\n\n"
        "🪪 **Une fois envoyé, ton dossier sera transmis "
        "au staff pour validation.**"
    )

    try:

        await member.send(
            message,
            view=PasseportView(),
        )

        print(
            f"📨 Passeport envoyé en MP à {member}"
        )

        return True

    except discord.Forbidden:

        print(
            f"⚠️ Impossible d'envoyer le MP à {member}"
        )

        return False

    except discord.HTTPException as erreur:

        print(
            f"❌ Erreur MP {member} : {erreur}"
        )

        return False


# =========================================================
# EVENT BOT READY
# =========================================================

@bot.event
async def on_ready():

    print("")
    print("========================================")
    print("🤖 BOT LIFEWORLD")
    print("========================================")
    print(
        f"✅ {bot.user} est connecté !"
    )
    print(
        f"📡 Connecté à {len(bot.guilds)} serveur(s)"
    )
    print("")
    print("🧪 Commandes :")
    print("   /test")
    print("   /test_complet")
    print("   /test_bienvenue")
    print("   /reset_douanes")
    print("")
    print("🚪 Système douanes :")
    print("   🚫 Aucun renommage nominatif")
    print("   🚫 Aucune douane nominative")
    print("   👤 Le joueur choisit le vocal indiqué")
    print("   🎙️ Libération si vocal vide 15 min")
    print("   ⏱️ Libération après 1h maximum")
    print("")
    print("👋 Système bienvenue :")
    print("   ✅ Message automatique à chaque nouvel arrivant")
    print("   👤 Nom du nouveau joueur affiché")
    print("========================================")
    print("")


# =========================================================
# NOUVEAU MEMBRE
# =========================================================

@bot.event
async def on_member_join(member):

    print(
        f"👤 Nouveau membre : {member} ({member.id})"
    )

    # =====================================================
    # ROLE EN ATTENTE
    # =====================================================

    role_attente = member.guild.get_role(
        ROLE_EN_ATTENTE_PAPIER_ID
    )

    if role_attente:

        try:

            await member.add_roles(
                role_attente,
                reason="Nouveau membre - attente de passeport",
            )

            print(
                f"📄 Rôle attente donné à {member}"
            )

        except discord.Forbidden:

            print(
                "❌ Impossible de donner le rôle attente."
            )

        except discord.HTTPException as erreur:

            print(
                f"❌ Erreur rôle attente : {erreur}"
            )

    # =====================================================
    # ENVOI DU PASSEPORT EN MP
    # =====================================================

    await envoyer_message_passeport(
        member
    )

    # =====================================================
    # MESSAGE AUTOMATIQUE DANS LE SALON BIENVENUE
    # =====================================================

    salon_bienvenue = bot.get_channel(
        BIENVENUE_ID
    )

    if salon_bienvenue is None:

        print(
            f"❌ Salon bienvenue introuvable : {BIENVENUE_ID}"
        )

        return

    # Nom affiché du joueur
    nom_joueur = member.display_name

    messages_bienvenue = [

        (
            f"👋 **Bienvenue {nom_joueur} sur LifeWorld !**\n\n"
            f"Bienvenue à toi {member.mention} ! "
            "Pose tes valises et prépare-toi à vivre ton aventure RP."
        ),

        (
            f"🎉 **Bienvenue {nom_joueur} !**\n\n"
            f"{member.mention} vient de rejoindre LifeWorld ! "
            "Souhaitez-lui la bienvenue. 👋"
        ),

        (
            f"🏙️ **Bienvenue {nom_joueur} sur LifeWorld !**\n\n"
            f"Salut {member.mention} ! "
            "Ta nouvelle vie commence maintenant."
        ),

        (
            f"🪪 **Bienvenue {nom_joueur} !**\n\n"
            f"{member.mention}, ton aventure LifeWorld commence ici. "
            "Pense à suivre les étapes pour créer ton passeport RP."
        ),

        (
            f"🚗 **Bienvenue {nom_joueur} !**\n\n"
            f"{member.mention} vient d'arriver en ville ! "
            "Bonne aventure et bon RP à toi. 😄"
        ),

        (
            f"🎭 **Bienvenue {nom_joueur} !**\n\n"
            f"{member.mention} vient de rejoindre LifeWorld ! "
            "À toi maintenant d'écrire ton histoire."
        ),

        (
            f"👀 **Oh ! {nom_joueur} vient d'arriver !**\n\n"
            f"Bienvenue {member.mention} sur LifeWorld ! "
            "Quelqu'un lui montre les alentours ? 😄"
        ),

        (
            f"🏠 **Bienvenue {nom_joueur} !**\n\n"
            f"{member.mention}, installe-toi bien et profite de ton aventure "
            "sur LifeWorld !"
        ),

        (
            f"🚨 **NOUVEL ARRIVANT !**\n\n"
            f"Bienvenue **{nom_joueur}** ! 👋\n"
            f"Tout le monde souhaite la bienvenue à {member.mention} !"
        ),

        (
            f"🍻 **Bienvenue {nom_joueur} !**\n\n"
            f"Salut {member.mention} ! "
            "Bienvenue dans la ville et bon courage pour ta nouvelle vie. 😄"
        ),
    ]

    try:

        message = random.choice(
            messages_bienvenue
        )

        await salon_bienvenue.send(
            message
        )

        print(
            f"👋 Message bienvenue envoyé pour {member.display_name}"
        )

    except discord.Forbidden:

        print(
            "❌ Impossible d'écrire dans le salon bienvenue."
        )

    except discord.HTTPException as erreur:

        print(
            f"❌ Erreur message bienvenue : {erreur}"
        )


# =========================================================
# /TEST
# =========================================================

@bot.tree.command(
    name="test",
    description="Teste l'envoi du passeport en MP",
)
async def test(interaction):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée sur le serveur.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        "🧪 **Test LifeWorld lancé !**\n\n"
        "📨 Je t'envoie maintenant le passeport en MP.",
        ephemeral=True,
    )

    resultat = await envoyer_message_passeport(
        interaction.user
    )

    if resultat:

        await interaction.followup.send(
            "✅ **MP envoyé !**\n\n"
            "Va dans tes messages privés avec le bot "
            "et clique sur **🪪 Créer mon passeport**.",
            ephemeral=True,
        )

    else:

        await interaction.followup.send(
            "❌ Je n'arrive pas à t'envoyer de MP.\n\n"
            "Vérifie que tes messages privés sont autorisés.",
            ephemeral=True,
        )


# =========================================================
# /TEST_COMPLET
# =========================================================

@bot.tree.command(
    name="test_complet",
    description="Crée un faux dossier WL pour tester la validation",
)
async def test_complet(interaction):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée sur le serveur.",
            ephemeral=True,
        )
        return

    if not interaction.user.guild_permissions.administrator:

        await interaction.response.send_message(
            "❌ Cette commande est réservée au staff.",
            ephemeral=True,
        )
        return

    salon = bot.get_channel(
        HISTOIRES_RP_ID
    )

    if salon is None:

        await interaction.response.send_message(
            "❌ Le salon des histoires RP est introuvable.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title="🧪 TEST - Nouveau passeport RP",
        description=(
            "Ceci est un dossier de test créé avec `/test_complet`."
        ),
        color=discord.Color.blue(),
    )

    embed.add_field(
        name="👤 Joueur",
        value=(
            f"{interaction.user.mention}\n"
            f"ID : `{interaction.user.id}`"
        ),
        inline=False,
    )

    embed.add_field(
        name="Nom RP",
        value="TEST",
        inline=True,
    )

    embed.add_field(
        name="Prénom RP",
        value="LifeWorld",
        inline=True,
    )

    embed.add_field(
        name="Âge RP",
        value="25",
        inline=True,
    )

    embed.add_field(
        name="📖 Histoire / Lore",
        value=(
            "Ceci est une histoire RP de test "
            "pour vérifier le fonctionnement de la WL."
        ),
        inline=False,
    )

    embed.set_footer(
        text="🧪 Dossier de test"
    )

    try:

        await salon.send(
            embed=embed,
            view=DossierStaffView(),
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ Je n'ai pas la permission d'écrire dans ce salon.",
            ephemeral=True,
        )
        return

    except discord.HTTPException as erreur:

        print(
            f"❌ Erreur test complet : {erreur}"
        )

        await interaction.response.send_message(
            "❌ Impossible de créer le dossier de test.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        "✅ **Test complet créé !**\n\n"
        f"Va dans <#{HISTOIRES_RP_ID}>.\n\n"
        "Tu peux maintenant tester :\n"
        "📅 Proposer un rendez-vous\n"
        "✅ Valider la WL\n"
        "❌ Refuser la WL",
        ephemeral=True,
    )


# =========================================================
# /TEST_BIENVENUE
# =========================================================

@bot.tree.command(
    name="test_bienvenue",
    description="Teste le message de bienvenue public",
)
async def test_bienvenue(interaction):

    salon = bot.get_channel(
        BIENVENUE_ID
    )

    if salon is None:

        await interaction.response.send_message(
            "❌ Salon bienvenue introuvable.",
            ephemeral=True,
        )
        return

    nom_joueur = interaction.user.display_name

    try:

        await salon.send(
            "🧪 **TEST BIENVENUE**\n\n"
            f"👋 **Bienvenue {nom_joueur} !**\n"
            f"Salut {interaction.user.mention}, bienvenue "
            "**sur LifeWorld** ! 🎉"
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ Je n'ai pas la permission d'écrire dans le salon.",
            ephemeral=True,
        )
        return

    except discord.HTTPException as erreur:

        print(
            f"❌ Erreur test bienvenue : {erreur}"
        )

        await interaction.response.send_message(
            "❌ Impossible d'envoyer le message.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        "✅ Message de bienvenue envoyé.",
        ephemeral=True,
    )


# =========================================================
# /RESET_DOUANES
# =========================================================

@bot.tree.command(
    name="reset_douanes",
    description="Remet les trois douanes à leur état libre",
)
async def reset_douanes(interaction):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée sur le serveur.",
            ephemeral=True,
        )
        return

    if not interaction.user.guild_permissions.administrator:

        await interaction.response.send_message(
            "❌ Cette commande est réservée au staff.",
            ephemeral=True,
        )
        return

    resultat = []

    for channel_id, nom_original in DOUANES.items():

        salon = interaction.guild.get_channel(
            channel_id
        )

        if salon is None:

            resultat.append(
                f"❌ `{nom_original}` : salon introuvable"
            )
            continue

        # =================================================
        # ANNULER TACHE
        # =================================================

        tache = taches_liberation.get(
            channel_id
        )

        if tache and not tache.done():

            tache.cancel()

        # =================================================
        # SUPPRIMER RESERVATION
        # =================================================

        reservations_douanes.pop(
            channel_id,
            None,
        )

        # =================================================
        # NOM ORIGINAL
        # =================================================

        try:

            if salon.name != nom_original:

                await salon.edit(
                    name=nom_original,
                    reason="Reset manuel des douanes",
                )

            resultat.append(
                f"✅ `{nom_original}` : libre"
            )

        except discord.HTTPException as erreur:

            resultat.append(
                f"❌ `{nom_original}` : erreur ({erreur})"
            )

    await interaction.response.send_message(
        "🔄 **Reset des douanes terminé.**\n\n"
        + "\n".join(resultat),
        ephemeral=True,
    )


# =========================================================
# SETUP HOOK
# =========================================================

@bot.event
async def setup_hook():

    bot.add_view(
        PasseportView()
    )

    bot.add_view(
        DossierStaffView()
    )

    bot.add_view(
        RendezVousView()
    )

    try:

        synced = await bot.tree.sync()

        print(
            f"🔄 {len(synced)} commande(s) slash synchronisée(s)"
        )

        for command in synced:

            print(
                f"   /{command.name} - "
                f"{command.description}"
            )

    except Exception as erreur:

        print(
            f"❌ Erreur synchronisation commandes : {erreur}"
        )


# =========================================================
# LANCEMENT
# =========================================================

if not TOKEN:

   print(
    "❌ ERREUR : DISCORD_TOKEN est absent des variables Railway"
)

else:

    bot.run(TOKEN)
import discord
from discord.ext import commands
from discord import ui, Interaction
import json
import asyncio
import logging

# Configuración básica del logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/onboarding.log"),
        logging.StreamHandler()
    ]
)

class PreguntaHandler:
    def __init__(self, bot, member, preguntas, data_file, lock):
        self.bot = bot
        self.member = member
        self.preguntas = preguntas
        self.respuestas = {}
        self.data_file = data_file
        self.lock = lock
        self.current_question = 0

    async def start(self):
        await self.send_next_question()

    async def send_next_question(self):
        if self.current_question < len(self.preguntas):
            pregunta = self.preguntas[self.current_question]
            dm_channel = await self.member.create_dm()
            await dm_channel.send(pregunta)
            await self.wait_for_response()
        else:
            await self.finalize_onboarding()

    async def wait_for_response(self):
        try:
            def check(msg):
                return msg.author == self.member and isinstance(msg.channel, discord.DMChannel)

            msg = await self.bot.wait_for("message", check=check, timeout=300)  # 5 minutos de espera
            pregunta_actual = self.preguntas[self.current_question]
            self.respuestas[pregunta_actual] = msg.content
            self.current_question += 1
            await self.send_next_question()
        except asyncio.TimeoutError:
            dm_channel = await self.member.create_dm()
            await dm_channel.send("Tiempo agotado. Por favor, vuelve a intentar el proceso.")
            logging.warning(f"Tiempo agotado para {self.member.name}#{self.member.discriminator}")

    async def finalize_onboarding(self):
        async with self.lock:
            with open(self.data_file, "r") as f:
                data = json.load(f)

            personajes_disponibles = data.get("disponibles", [])
            if not personajes_disponibles:
                dm_channel = await self.member.create_dm()
                await dm_channel.send("Lo siento, no hay personajes disponibles en este momento.")
                logging.warning(f"No hay personajes disponibles para {self.member.name}#{self.member.discriminator}")
                return

            dm_channel = await self.member.create_dm()
            await dm_channel.send(
                "Por favor, selecciona tu personaje del siguiente menú:",
                view=PersonajeDropdownView(personajes_disponibles, self.member, self.data_file, self.lock, self.bot, self.respuestas)
            )

class PersonajeDropdown(ui.Select):
    def __init__(self, personajes, member, data_file, lock, bot, respuestas):
        self.member = member
        self.data_file = data_file
        self.lock = lock
        self.bot = bot
        self.respuestas = respuestas

        opciones = [
            discord.SelectOption(label=personaje["nombre"], description=f"Región: {personaje['region']}" if "region" in personaje else "Región desconocida")
            for personaje in personajes
        ]

        super().__init__(
            placeholder="Selecciona tu personaje...",
            min_values=1,
            max_values=1,
            options=opciones[:25]  # Discord permite un máximo de 25 opciones
        )

    async def callback(self, interaction: Interaction):
        personaje_seleccionado = self.values[0]
        async with self.lock:
            with open(self.data_file, "r") as f:
                data = json.load(f)

            personaje = next(
                (p for p in data["disponibles"] if p["nombre"] == personaje_seleccionado), None
            )
            if not personaje:
                await interaction.response.send_message(
                    "Este personaje ya fue seleccionado por otro usuario. Por favor, selecciona otro.", ephemeral=True
                )
                return

            data["disponibles"].remove(personaje)
            data["asignados"][str(self.member.id)] = personaje

            with open(self.data_file, "w") as f:
                json.dump(data, f, indent=4)

        await interaction.response.send_message(
            f"Has seleccionado el personaje **{personaje_seleccionado}** de la región **{personaje.get('region', 'desconocida')}**. ¡Bienvenido al servidor!",
            ephemeral=True
        )

        # Cambiar el apodo del miembro al nombre del personaje seleccionado
        try:
            await self.member.edit(nick=personaje_seleccionado)
            logging.info(f"Apodo de {self.member.name}#{self.member.discriminator} cambiado a {personaje_seleccionado}")
        except discord.Forbidden:
            logging.warning(f"No se pudo cambiar el apodo de {self.member.name}#{self.member.discriminator}. Permisos insuficientes.")
        except Exception as e:
            logging.error(f"Error al cambiar el apodo de {self.member.name}#{self.member.discriminator}: {e}")

        # Crear un embed para el mensaje de bienvenida
        canal_bienvenida = discord.utils.get(self.member.guild.text_channels, name="bienvenida")
        if canal_bienvenida:
            # Generar el URL de la imagen del personaje
            personaje_image_url = f"https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{personaje_seleccionado}_0.jpg"

            embed = discord.Embed(
                title=f"¡Bienvenido {self.member.display_name}! 🎉",
                description=f"Se unió al servidor y ha elegido a **{personaje_seleccionado}**.",
                color=discord.Color.blue()
            )
            embed.add_field(name="Edad", value=self.respuestas.get('¿Cuál es tu edad?'), inline=True)
            embed.add_field(name="Nick", value=self.respuestas.get('¿Cuál será tu nick?'), inline=True)
            embed.add_field(name="Hobbies", value=self.respuestas.get('¿Cuáles son tus hobbies?'), inline=False)
            embed.add_field(name="Región", value=personaje.get('region', 'desconocida'), inline=True)
            embed.add_field(name="Personaje", value=personaje_seleccionado, inline=True)
            embed.set_thumbnail(url=personaje_image_url)
            embed.set_footer(text="¡Disfruta tu estadía!", icon_url=self.member.avatar.url if self.member.avatar else None)

            await canal_bienvenida.send(embed=embed)

class PersonajeDropdownView(ui.View):
    def __init__(self, personajes, member, data_file, lock, bot, respuestas):
        super().__init__()
        self.add_item(PersonajeDropdown(personajes, member, data_file, lock, bot, respuestas))

class Onboarding(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_file = './data/personajes_disponibles.json'
        self.lock = asyncio.Lock()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        logging.info(f"Nuevo miembro detectado: {member.name}#{member.discriminator} (ID: {member.id})")
        try:
            preguntas = ["¿Cuál es tu edad?", "¿Cuál será tu nick?", "¿Cuáles son tus hobbies?"]
            handler = PreguntaHandler(self.bot, member, preguntas, self.data_file, self.lock)
            await handler.start()
        except Exception as e:
            logging.error(f"Error en on_member_join para {member.name}#{member.discriminator}: {e}")
            try:
                dm_channel = await member.create_dm()
                await dm_channel.send("Hubo un error al configurar tu perfil. Por favor, contacta a un administrador.")
            except:
                pass

async def setup(bot):
    await bot.add_cog(Onboarding(bot))

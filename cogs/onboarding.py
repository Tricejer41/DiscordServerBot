import discord
from discord.ext import commands
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

DATA_FILE = "./data/personajes_disponibles.json"

def cargar_datos():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def guardar_datos(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

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
        logging.info(f"[START] Iniciando proceso de preguntas para {self.member.name}")
        await self.send_next_question()

    async def send_next_question(self):
        if self.current_question < len(self.preguntas):
            pregunta = self.preguntas[self.current_question]
            dm_channel = await self.member.create_dm()
            logging.info(f"[SEND_NEXT_QUESTION] Enviando pregunta '{pregunta}' a {self.member.name}")
            await dm_channel.send(pregunta)
        else:
            logging.info(f"[SEND_NEXT_QUESTION] Se han hecho todas las preguntas a {self.member.name}. Finalizando onboarding.")
            await self.finalize_onboarding()

    async def process_response(self, message):
        """Procesa cada mensaje de respuesta que envía el usuario por DM."""
        if message.author != self.member or not isinstance(message.channel, discord.DMChannel):
            return

        pregunta_actual = self.preguntas[self.current_question]
        logging.info(f"[PROCESS_RESPONSE] Recibida respuesta de {self.member.name} a '{pregunta_actual}'")
        self.respuestas[pregunta_actual] = message.content
        self.current_question += 1
        await self.send_next_question()

    async def finalize_onboarding(self):
        """Muestra la lista de campeones al final y maneja la selección."""
        async with self.lock:
            data = cargar_datos()
            personajes_disponibles = sorted(data.get("disponibles", []), key=lambda x: x["nombre"].lower())

            if not personajes_disponibles:
                dm_channel = await self.member.create_dm()
                await dm_channel.send("Lo siento, no hay personajes disponibles en este momento.")
                logging.warning(f"[FINALIZE] No hay personajes disponibles para {self.member.name}")
                return

            # Crear mensaje formateado con IDs y personajes
            mensaje_personajes = [
                f"{i + 1} - {p['nombre']} (Región: {p['region']})"
                for i, p in enumerate(personajes_disponibles)
            ]

            # Dividir el mensaje en fragmentos de máximo 2000 caracteres
            mensajes_fragmentados = []
            fragmento_actual = ""
            for linea in mensaje_personajes:
                if len(fragmento_actual) + len(linea) + 1 > 2000:
                    mensajes_fragmentados.append(fragmento_actual)
                    fragmento_actual = linea + "\n"
                else:
                    fragmento_actual += linea + "\n"

            if fragmento_actual:
                mensajes_fragmentados.append(fragmento_actual)

            dm_channel = await self.member.create_dm()

            logging.info(f"[FINALIZE] Enviando lista de personajes a {self.member.name} en {len(mensajes_fragmentados)} fragmentos.")

            for fragmento in mensajes_fragmentados:
                await dm_channel.send(fragmento)

            await dm_channel.send("Por favor, responde con el número correspondiente al personaje que deseas seleccionar:")

            def check(m):
                return m.author == self.member and isinstance(m.channel, discord.DMChannel)

            try:
                msg = await self.bot.wait_for("message", check=check, timeout=300)
                seleccion = int(msg.content.strip()) - 1

                if 0 <= seleccion < len(personajes_disponibles):
                    personaje = personajes_disponibles[seleccion]
                    data["disponibles"].remove(personaje)
                    data["asignados"][self.member.name] = {
                        "id": self.member.id,
                        "nombre": personaje["nombre"],
                        "region": personaje["region"],
                        "mensajePresentacionId": None  # lo guardaremos luego
                    }
                    guardar_datos(data)

                    logging.info(f"[FINALIZE] {self.member.name} eligió {personaje['nombre']} ({personaje['region']}).")

                    await dm_channel.send(
                        f"Has seleccionado a **{personaje['nombre']}** de la región **{personaje['region']}**. ¡Bienvenido!"
                    )

                    # Cambiar apodo del usuario
                    try:
                        await self.member.edit(nick=personaje["nombre"])
                        logging.info(f"[FINALIZE] Se cambió el apodo de {self.member.name} a {personaje['nombre']}")
                    except discord.Forbidden:
                        logging.warning(f"[FINALIZE] Permisos insuficientes para cambiar apodo de {self.member.name}")

                    # Mensaje en canal de bienvenida
                    canal_bienvenida = discord.utils.get(self.member.guild.text_channels, name="bienvenida")
                    if canal_bienvenida:
                        imagen_url = f"https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{personaje['nombre']}_0.jpg"
                        embed = discord.Embed(
                            title=f"¡Bienvenido {self.member.display_name}! 🎉",
                            description=f"Se unió al servidor y ha elegido a **{personaje['nombre']}**.",
                            color=discord.Color.blue()
                        )
                        embed.add_field(name="Edad", value=self.respuestas.get('¿Cuál es tu edad?'), inline=True)
                        embed.add_field(name="Nick", value=self.respuestas.get('¿Cuál será tu nick?'), inline=True)
                        embed.add_field(name="Hobbies", value=self.respuestas.get('¿Cuáles son tus hobbies?'), inline=False)
                        embed.add_field(name="Región", value=personaje['region'], inline=True)
                        embed.set_thumbnail(url=imagen_url)
                        embed.set_footer(text="¡Disfruta tu estadía!")

                        try:
                            msg_embed = await canal_bienvenida.send(embed=embed)
                            logging.info(f"[FINALIZE] Mensaje de bienvenida enviado en canal '{canal_bienvenida.name}'.")

                            # Guardamos el ID del mensaje para que pueda ser borrado si el usuario sale
                            data["asignados"][self.member.name]["mensajePresentacionId"] = msg_embed.id
                            guardar_datos(data)

                        except Exception as e:
                            logging.error(f"[FINALIZE] Error al enviar el mensaje de bienvenida: {e}")
                    else:
                        logging.warning("[FINALIZE] No se encontró el canal 'bienvenida'.")
                else:
                    await dm_channel.send("Número inválido. Proceso cancelado.")
                    logging.warning(f"[FINALIZE] {self.member.name} ingresó un número inválido al seleccionar personaje.")
            except (ValueError, asyncio.TimeoutError):
                await dm_channel.send("Tiempo agotado o entrada inválida. Por favor, vuelve a intentarlo más tarde.")
                logging.warning(f"[FINALIZE] Tiempo agotado o entrada inválida al seleccionar personaje para {self.member.name}.")

class Onboarding(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_file = DATA_FILE
        self.lock = asyncio.Lock()
        self.pregunta_handlers = {}

    @commands.Cog.listener()
    async def on_member_join(self, member):
        logging.info(f"[on_member_join] Se unió: {member.name} (ID: {member.id})")
        preguntas = ["¿Cuál es tu edad?", "¿Cuál será tu nick?", "¿Cuáles son tus hobbies?"]
        handler = PreguntaHandler(self.bot, member, preguntas, self.data_file, self.lock)
        self.pregunta_handlers[member.id] = handler
        await handler.start()

    @commands.Cog.listener()
    async def on_message(self, message):
        logging.debug(f"[on_message] Recibido mensaje de {message.author} en {message.channel}")
        if message.author.id in self.pregunta_handlers:
            logging.debug(f"[on_message] Procesando respuesta de {message.author}")
            await self.pregunta_handlers[message.author.id].process_response(message)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        async with self.lock:
            data = cargar_datos()
            if member.name in data["asignados"]:
                asignado = data["asignados"].pop(member.name)
                personaje_restaurado = {
                    "nombre": asignado["nombre"],
                    "region": asignado["region"]
                }
                data["disponibles"].append(personaje_restaurado)

                # Borrado del mensaje de bienvenida, si existe
                msg_id = asignado.get("mensajePresentacionId")
                if msg_id:
                    canal_bienvenida = discord.utils.get(member.guild.text_channels, name="bienvenida")
                    if canal_bienvenida:
                        try:
                            msg_to_delete = await canal_bienvenida.fetch_message(msg_id)
                            await msg_to_delete.delete()
                            logging.info(f"[on_member_remove] Borrado el mensaje de presentación para {member.name}.")
                        except discord.NotFound:
                            logging.warning("[on_member_remove] El mensaje de presentación ya no existe.")
                        except discord.Forbidden:
                            logging.warning("[on_member_remove] Permisos insuficientes para borrar el mensaje de presentación.")
                        except Exception as e:
                            logging.error(f"[on_member_remove] Error al borrar mensaje de bienvenida: {e}")

                guardar_datos(data)
                logging.info(f"[on_member_remove] Personaje {asignado['nombre']} ha sido liberado para {member.name}.")

async def setup(bot):
    await bot.add_cog(Onboarding(bot))

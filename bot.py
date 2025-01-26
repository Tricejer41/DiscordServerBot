import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import logging
import asyncio

async def main():
    # Configuración de logging
    logging.basicConfig(
        filename='./logs/bot.log',
        level=logging.INFO,
        format='%(asctime)s:%(levelname)s:%(name)s: %(message)s'
    )

    # Cargar variables de entorno desde .env
    load_dotenv()
    TOKEN = os.getenv('TOKEN')

    if not TOKEN:
        logging.error("El token no está configurado. Revisa tu archivo .env.")
        return

    # Configurar intents
    intents = discord.Intents.default()
    intents.members = True  # Necesario para detectar nuevos miembros
    intents.messages = True
    intents.reactions = True
    intents.message_content = True  # Necesario para acceder al contenido de los mensajes

    # Inicializar el bot
    bot = commands.Bot(command_prefix='!', intents=intents)

    # Cargar todos los cogs automáticamente
    initial_extensions = [
        f'cogs.{filename[:-3]}'
        for filename in os.listdir('./cogs')
        if filename.endswith('.py')
    ]

    for extension in initial_extensions:
        try:
            await bot.load_extension(extension)
            logging.info(f'Cog cargado: {extension}')
        except Exception as e:
            logging.error(f'Error al cargar {extension}: {e}')

    @bot.event
    async def on_ready():
        print(f'Bot conectado como {bot.user}')
        logging.info(f'Bot conectado como {bot.user}')

    @bot.event
    async def on_command_error(ctx, error):
        if isinstance(error, commands.CommandNotFound):
            await ctx.send('Comando no encontrado.')
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send('Faltan argumentos para este comando.')
        elif isinstance(error, commands.BadArgument):
            await ctx.send('Argumentos inválidos proporcionados.')
        else:
            await ctx.send('Ocurrió un error al ejecutar el comando.')
            logging.error(f'Error en comando {ctx.command}: {error}')

    await bot.start(TOKEN)

if __name__ == '__main__':
    asyncio.run(main())

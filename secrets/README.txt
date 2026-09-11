Docker secrets are read from this directory by docker-compose.yml.

Compose validates these files before it starts any service, so build the image and
create both files before the first `docker compose up`:

  docker compose build bot
  printf '%s' 'YOUR_BOT_TOKEN' > secrets/discord_token
  docker run --rm --entrypoint python verification-bot:latest \
      -m verification_bot.logtools generate-key > secrets/log_encryption_key
  chmod 600 secrets/*

Neither file is tracked by git. Back up secrets/log_encryption_key somewhere safe:
without it, existing log files cannot be read.

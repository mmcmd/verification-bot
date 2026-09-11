Docker secrets are read from this directory by docker-compose.yml.

Create the two files before the first `docker compose up`:

  printf '%s' 'YOUR_BOT_TOKEN' > secrets/discord_token
  docker run --rm verification-bot:latest \
      python -m verification_bot.logtools generate-key > secrets/log_encryption_key
  chmod 600 secrets/*

Neither file is tracked by git. Back up secrets/log_encryption_key somewhere safe:
without it, existing log files cannot be read.

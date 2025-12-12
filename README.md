# archipelago-configs

My configs for https://archipelago.gg/

This repo also contains tools for more CLI-ergonomic use of the Achipelago software suite.
See `./cli.py --help` and `./apworld_manager.py --help`.

## Cheese Tracker

`cd cheese` and `docker-compose up`

## Jigsaw

https://jigsaw-ap.netlify.app/ requires the archipelago server serve `wss:` over TLS.
However, most clients (such as all the Launcher ones) do not support `wss:`, so you need to expose both a TLS and non-TLS port and use the correct one from each client.

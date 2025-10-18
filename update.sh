#!/usr/bin/env bash

# Update, build & install script for server

git pull
go build -o hr-demo-app-server ./cmd/server/main.go
sudo systemctl stop hr-demo-app-server
sudo cp hr-demo-app-server /usr/local/bin
sudo systemctl start hr-demo-app-server

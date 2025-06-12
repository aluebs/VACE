#!/bin/bash

# Cloudflare Tunnel Setup Script for VACE Server
# This creates a secure tunnel to make your local server accessible externally

echo "Setting up Cloudflare Tunnel for VACE Server..."

# Check if cloudflared is installed
if ! command -v cloudflared &> /dev/null; then
    echo "Installing cloudflared..."
    
    # Detect OS and install accordingly
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
        sudo dpkg -i cloudflared-linux-amd64.deb
        rm cloudflared-linux-amd64.deb
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        brew install cloudflare/cloudflare/cloudflared
    else
        echo "Please install cloudflared manually from: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/"
        exit 1
    fi
fi

echo "Cloudflared installed successfully!"
echo ""
echo "To create a tunnel:"
echo "1. Start your VACE server: python vace_server.py"
echo "2. In another terminal, run: cloudflared tunnel --url http://localhost:5000"
echo ""
echo "This will give you a public URL like: https://random-words-123.trycloudflare.com"
echo "The tunnel will stay active as long as the command is running."
echo ""
echo "For a permanent tunnel:"
echo "1. Login: cloudflared tunnel login"
echo "2. Create tunnel: cloudflared tunnel create vace-server"
echo "3. Configure and run the tunnel"
echo ""
echo "Quick start command:"
echo "cloudflared tunnel --url http://localhost:5000" 
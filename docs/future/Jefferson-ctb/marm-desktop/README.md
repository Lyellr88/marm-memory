# MARM Desktop v2.1

<div align="center">
  <img src="src-tauri/icons/icon.svg" width="128" height="128" alt="MARM Desktop">
  <h3>Native Desktop Companion for MARM Memory-Enhanced AI</h3>
  <p>Real-time monitoring and control of MARM sessions with Claude Code</p>
</div>

## ✨ Features

- 🔍 **Observer Mode**: Monitor Claude Code MARM interactions in real-time
- 🎯 **Direct Query**: Independent MARM session control
- 📂 **Session Management**: View and switch between MARM sessions/projects
- ⚙️ **Settings**: Configure connection and preferences
- 🎨 **Modern UI**: Glassmorphism design with native performance
- 🚀 **Cross-Platform**: Windows, macOS, Linux support

## 🏗️ Architecture

```
Claude Code (Local) ↗
                     → fastmcp.cloud → MARM MCP Server v2.1
MARM Desktop App ↗                    ↑ Auto-initialization
                                      ↑ Session sharing
                                      ↑ Real-time sync
```

## 📦 Download

### Automatic Builds (Recommended)

Download the latest version from [GitHub Releases](https://github.com/jeffersonwarrior/MARM-Systems/releases):

- **macOS**: `MARM-Desktop-macOS-Universal.dmg` (Intel + Apple Silicon)
- **Windows**: `MARM-Desktop-Windows-x86_64.exe` or `.msi`  
- **Linux**: `MARM-Desktop-Linux-x86_64.AppImage` or `.deb`

### Development Builds

Latest development builds are available as GitHub Actions artifacts from the [Actions tab](https://github.com/jeffersonwarrior/MARM-Systems/actions).

## 🛠️ Build from Source

### Prerequisites

- **Node.js** 18+ and npm
- **Rust** 1.70+ (install from [rustup.rs](https://rustup.rs/))
- **System dependencies**:
  - **macOS**: Xcode Command Line Tools
  - **Ubuntu**: `sudo apt-get install libgtk-3-dev libwebkit2gtk-4.0-dev libappindicator3-dev librsvg2-dev patchelf`
  - **Windows**: Microsoft C++ Build Tools

### Build Steps

```bash
# Clone the repository
git clone https://github.com/jeffersonwarrior/MARM-Systems.git
cd MARM-Systems/marm-desktop

# Install dependencies
npm install

# Generate app icons (optional, requires ImageMagick)
npm run icons

# Build for development
npm run dev

# Build for production
npm run build
```

### Icon Generation

To generate app icons from the SVG source:

```bash
# Install ImageMagick and Inkscape (for best quality)
# macOS: brew install imagemagick inkscape
# Ubuntu: sudo apt-get install imagemagick inkscape

# Generate all required icon formats
npm run icons
```

## 🚀 Usage

1. **Launch MARM Desktop**
2. **Connect** to the MARM MCP server (auto-configured to use fastmcp.cloud)
3. **Choose your mode**:
   - **Observer**: Watch Claude Code MARM activity
   - **Direct**: Control MARM sessions independently
   - **Sessions**: Browse and switch between sessions

## 🔧 Configuration

### Server Settings

- **Default URL**: `https://marm-systems.fastmcp.app/mcp`
- **Auto-connect**: Enabled by default
- **Polling interval**: 2 seconds for real-time updates

### Session Management

- Sessions are shared between Claude Code and Desktop App
- Real-time synchronization of activity and logs
- Automatic session discovery

## 🛡️ Security

- No API keys stored locally
- OAuth authentication via fastmcp.cloud
- Secure WebSocket connections for real-time updates

## 🧩 Development

### Tech Stack

- **Backend**: Rust (Tauri)
- **Frontend**: Vanilla JavaScript + HTML5
- **Build System**: Vite
- **Icons**: SVG with automated conversion

### Project Structure

```
marm-desktop/
├── src/                 # Frontend source
├── src-tauri/           # Rust backend
│   ├── src/main.rs     # Main application logic
│   ├── Cargo.toml      # Rust dependencies
│   └── icons/          # App icons
├── package.json        # Node.js config
└── vite.config.js      # Vite config
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test on multiple platforms
5. Submit a pull request

## 📄 License

MIT License - see [LICENSE](../LICENSE) for details.

## 🤝 Support

- **Issues**: [GitHub Issues](https://github.com/jeffersonwarrior/MARM-Systems/issues)
- **Discussions**: [GitHub Discussions](https://github.com/jeffersonwarrior/MARM-Systems/discussions)

---

<div align="center">
  <p>Built with ❤️ using <a href="https://tauri.app/">Tauri</a></p>
  <p>Part of the <a href="../">MARM v2.1 Ecosystem</a></p>
</div>
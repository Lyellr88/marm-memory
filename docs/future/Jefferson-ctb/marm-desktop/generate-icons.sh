#!/bin/bash

# MARM Desktop Icon Generator
# Generates all required icon formats from the base SVG

cd "$(dirname "$0")"
ICON_DIR="src-tauri/icons"
SVG_SOURCE="$ICON_DIR/icon.svg"

echo "🎨 Generating MARM Desktop icons..."

# Create placeholder function for when tools aren't available
create_placeholder_png() {
    local size=$1
    local filename=$2
    
    # Create a simple colored square as placeholder
    echo "  ⚠️  Creating placeholder $filename (${size}x${size})"
    
    # This creates a minimal PNG header for a solid color square
    # In production, this would be replaced by proper icon generation
    touch "$ICON_DIR/$filename"
}

# Check if ImageMagick is installed
if ! command -v convert &> /dev/null; then
    echo "⚠️  ImageMagick not found. Creating placeholder icons..."
    USE_PLACEHOLDERS=true
else
    USE_PLACEHOLDERS=false
    echo "✅ Using ImageMagick for icon generation"
fi

# Check if inkscape is available (better SVG rendering)
if command -v inkscape &> /dev/null; then
    RENDERER="inkscape"
    echo "✅ Using Inkscape for high-quality SVG rendering"
else
    RENDERER="imagemagick"
    echo "⚠️  Using ImageMagick (install Inkscape for better quality)"
fi

# Generate function
generate_icon() {
    local size=$1
    local filename=$2
    
    if [ "$USE_PLACEHOLDERS" = "true" ]; then
        create_placeholder_png $size "$filename"
        return
    fi
    
    if [ "$RENDERER" = "inkscape" ]; then
        inkscape "$SVG_SOURCE" -w $size -h $size -o "$ICON_DIR/$filename"
    else
        convert "$SVG_SOURCE" -resize "${size}x${size}" "$ICON_DIR/$filename"
    fi
    
    echo "  ✓ Generated $filename (${size}x${size})"
}

# PNG Icons (various sizes)
generate_icon 32 "32x32.png"
generate_icon 128 "128x128.png" 
generate_icon 256 "128x128@2x.png"
generate_icon 256 "256x256.png"
generate_icon 512 "512x512.png"
generate_icon 1024 "1024x1024.png"

# Windows ICO (multi-size)
if command -v convert &> /dev/null; then
    convert "$SVG_SOURCE" -resize 16x16 "$ICON_DIR/icon-16.png"
    convert "$SVG_SOURCE" -resize 32x32 "$ICON_DIR/icon-32.png"
    convert "$SVG_SOURCE" -resize 48x48 "$ICON_DIR/icon-48.png"
    convert "$SVG_SOURCE" -resize 64x64 "$ICON_DIR/icon-64.png"
    convert "$SVG_SOURCE" -resize 128x128 "$ICON_DIR/icon-128.png"
    convert "$SVG_SOURCE" -resize 256x256 "$ICON_DIR/icon-256.png"
    
    convert "$ICON_DIR/icon-16.png" "$ICON_DIR/icon-32.png" "$ICON_DIR/icon-48.png" \
            "$ICON_DIR/icon-64.png" "$ICON_DIR/icon-128.png" "$ICON_DIR/icon-256.png" \
            "$ICON_DIR/icon.ico"
    
    # Cleanup intermediate files
    rm "$ICON_DIR"/icon-*.png
    echo "  ✓ Generated icon.ico (multi-size Windows icon)"
fi

# macOS ICNS
if command -v sips &> /dev/null && command -v iconutil &> /dev/null; then
    # Create iconset directory
    ICONSET_DIR="$ICON_DIR/icon.iconset"
    mkdir -p "$ICONSET_DIR"
    
    # Generate all required sizes for macOS
    sips -z 16 16 "$ICON_DIR/512x512.png" --out "$ICONSET_DIR/icon_16x16.png" > /dev/null 2>&1
    sips -z 32 32 "$ICON_DIR/512x512.png" --out "$ICONSET_DIR/icon_16x16@2x.png" > /dev/null 2>&1
    sips -z 32 32 "$ICON_DIR/512x512.png" --out "$ICONSET_DIR/icon_32x32.png" > /dev/null 2>&1
    sips -z 64 64 "$ICON_DIR/512x512.png" --out "$ICONSET_DIR/icon_32x32@2x.png" > /dev/null 2>&1
    sips -z 128 128 "$ICON_DIR/512x512.png" --out "$ICONSET_DIR/icon_128x128.png" > /dev/null 2>&1
    sips -z 256 256 "$ICON_DIR/512x512.png" --out "$ICONSET_DIR/icon_128x128@2x.png" > /dev/null 2>&1
    sips -z 256 256 "$ICON_DIR/512x512.png" --out "$ICONSET_DIR/icon_256x256.png" > /dev/null 2>&1
    sips -z 512 512 "$ICON_DIR/512x512.png" --out "$ICONSET_DIR/icon_256x256@2x.png" > /dev/null 2>&1
    sips -z 512 512 "$ICON_DIR/512x512.png" --out "$ICONSET_DIR/icon_512x512.png" > /dev/null 2>&1
    cp "$ICON_DIR/1024x1024.png" "$ICONSET_DIR/icon_512x512@2x.png"
    
    # Generate ICNS
    iconutil -c icns "$ICONSET_DIR" -o "$ICON_DIR/icon.icns"
    rm -rf "$ICONSET_DIR"
    echo "  ✓ Generated icon.icns (macOS icon)"
elif command -v png2icns &> /dev/null; then
    # Alternative method using png2icns
    png2icns "$ICON_DIR/icon.icns" "$ICON_DIR/512x512.png"
    echo "  ✓ Generated icon.icns (macOS icon)"
else
    echo "  ⚠️  Skipped icon.icns (macOS tools not available)"
fi

echo ""
echo "🎉 Icon generation complete!"
echo "📁 Icons created in: $ICON_DIR"
echo ""
echo "Generated files:"
ls -la "$ICON_DIR" | grep -E '\.(png|ico|icns)$' | awk '{print "  " $9 " (" $5 " bytes)"}'

echo ""
echo "🚀 Ready for Tauri build!"
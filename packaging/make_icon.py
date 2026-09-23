"""生成 app 图标：渐变圆角底 + 白色聊天气泡（SF Symbol）。packaging/build.sh 调用，产物 build/chat-jev.icns。"""

import subprocess
import sys
from pathlib import Path

from AppKit import (
    NSBezierPath,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSColor,
    NSCompositingOperationSourceAtop,
    NSDeviceRGBColorSpace,
    NSGradient,
    NSGraphicsContext,
    NSImage,
    NSImageSymbolConfiguration,
    NSMakeRect,
    NSRectFillUsingOperation,
)

SYMBOL = "bubble.left.and.text.bubble.right.fill"


def render(px: int) -> bytes:
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, px, px, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
    s = px / 1024
    inset = 100 * s                                   # macOS 图标网格：内容区 824/1024
    body = NSMakeRect(inset, inset, px - 2 * inset, px - 2 * inset)
    path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(body, 185 * s, 185 * s)
    top = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.98, 0.42, 0.52, 1)
    bottom = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.55, 0.30, 0.92, 1)
    NSGradient.alloc().initWithStartingColor_endingColor_(bottom, top).drawInBezierPath_angle_(path, 90)

    cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(430 * s, 0.3)
    sym = NSImage.imageWithSystemSymbolName_accessibilityDescription_(SYMBOL, None).imageWithSymbolConfiguration_(cfg)
    w, h = sym.size().width, sym.size().height
    tinted = NSImage.alloc().initWithSize_(sym.size())
    tinted.lockFocus()
    sym.drawInRect_(NSMakeRect(0, 0, w, h))
    NSColor.whiteColor().set()
    NSRectFillUsingOperation(NSMakeRect(0, 0, w, h), NSCompositingOperationSourceAtop)
    tinted.unlockFocus()
    tinted.drawInRect_(NSMakeRect((px - w) / 2, (px - h) / 2 - 10 * s, w, h))
    NSGraphicsContext.restoreGraphicsState()
    return bytes(rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None))


def main(out: str) -> None:
    iconset = Path(out).with_suffix(".iconset")
    iconset.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
            (iconset / name).write_bytes(render(size * scale))
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", out], check=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/chat-jev.icns")

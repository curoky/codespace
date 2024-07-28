import Foundation
import CoreServices

// Configuration table: [UTI : Target App Bundle ID]
let config: [String: String] = [
    // Text and Development types
    "public.text": "com.microsoft.VSCode",
    "public.plain-text": "com.microsoft.VSCode",
    "public.source-code": "com.microsoft.VSCode",
    "public.json": "com.microsoft.VSCode",
    "public.yaml": "com.microsoft.VSCode",
    "public.data": "com.microsoft.VSCode",

    // Log files
    "com.apple.log": "com.microsoft.VSCode",
    "public.log": "com.microsoft.VSCode",

    // Image types
    "public.image": "com.apple.Preview",
    "public.heic": "com.apple.Preview",
    "public.camera-raw-image": "com.apple.Preview"
]

func setDefaults() {
    print("🚀 Starting batch modification of file associations...")

    for (uti, bundleID) in config {
        let cfUTI = uti as CFString
        let cfBundleID = bundleID as CFString

        // LSSetDefaultRoleHandlerForContentType sets the default handler for a specific UTI.
        // The '.all' role covers editor, viewer, and shell roles.
        let status = LSSetDefaultRoleHandlerForContentType(cfUTI, .all, cfBundleID)

        if status == noErr {
            print("✅ Success: [\(uti)] -> [\(bundleID)]")
        } else {
            print("❌ Failed: [\(uti)], Error code: \(status)")
        }
    }

    print("\n✨ Batch update complete!")
    print("💡 Note: If Finder icons do not update immediately, try restarting Finder or waiting a few moments.")
}

setDefaults()

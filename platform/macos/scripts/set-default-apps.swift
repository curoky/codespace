import CoreServices
import Foundation

let associations: [(uti: String, bundleID: String)] = [
    ("public.text", "com.microsoft.VSCode"),
    ("public.plain-text", "com.microsoft.VSCode"),
    ("public.source-code", "com.microsoft.VSCode"),
    ("public.json", "com.microsoft.VSCode"),
    ("public.toml", "com.microsoft.VSCode"),
    ("public.yaml", "com.microsoft.VSCode"),
    ("public.data", "com.microsoft.VSCode"),
    ("com.apple.log", "com.microsoft.VSCode"),
    ("public.log", "com.microsoft.VSCode"),
    ("public.image", "com.apple.Preview"),
    ("public.heic", "com.apple.Preview"),
    ("public.camera-raw-image", "com.apple.Preview"),
]

var failed = false
for association in associations {
    let status = LSSetDefaultRoleHandlerForContentType(
        association.uti as CFString,
        .all,
        association.bundleID as CFString
    )
    if status == noErr {
        print("\(association.uti) -> \(association.bundleID)")
    } else {
        fputs(
            "error: failed to set \(association.uti) to \(association.bundleID): \(status)\n",
            stderr
        )
        failed = true
    }
}

if failed {
    exit(EXIT_FAILURE)
}

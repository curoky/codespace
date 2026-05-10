{
  nix.settings.experimental-features = [ "nix-command" "flakes" ];
  permittedInsecurePackages = [
     "zeronet-0.7.1"
  ];
  allowUnfree = true;
}

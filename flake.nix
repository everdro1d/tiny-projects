{
  description = "ipod-music-downloader development shell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          mutagen
        ]);
      in {
        devShells.default = pkgs.mkShell {
          name = "ipod-music-downloader";
          buildInputs = [
            pythonEnv
          ];

          shellHook = ''
            echo "ipod-music-downloader development environment"
            echo "Python version: $(python --version)"
            echo "Mount your ipod's Music folder to the ./music/Music folder"
            echo "Run with: python app.py"
          '';
        };
      });
}


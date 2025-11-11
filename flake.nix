{
  description = "spotify folder to playlist development shell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          python-dotenv
          spotipy
        ]);
      in {
        devShells.default = pkgs.mkShell {
          name = "spotify-folder-to-playlist";
          buildInputs = [
            pythonEnv
          ];

          shellHook = ''
            echo "Spotify folder -> playlist development environment"
            echo "Python version: $(python --version)"
            echo "Run with: python app.py"
          '';
        };
      });
}

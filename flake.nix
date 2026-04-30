{
  description = "Nix flake for hyprpaper-randomizer";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python3;
        pythonPackages = pkgs.python3Packages;
      in {
        packages.default = pythonPackages.buildPythonApplication rec {
          pname = "hyprpaper-randomizer";
          version = "1.0.0";
          src = ./.;
          format = "other";

          propagatedBuildInputs = with pythonPackages; [
            python
            pillow
            argcomplete
            pkgs.makeWrapper
          ];

          nativeBuildInputs = [ pkgs.makeWrapper pythonPackages.argcomplete ];

          # since upstream isn't using setuptools or poetry, install manually
          installPhase = ''
            runHook preInstall

            mkdir -p $out/share/${pname}
            cp -r . $out/share/${pname}/
            chmod +x $out/share/${pname}/hyprpaper-randomizer.py

            mkdir -p $out/bin

            cp -s $out/share/${pname}/hyprpaper-randomizer.py $out/bin/hyprpaper-randomizer

            wrapProgram $out/bin/hyprpaper-randomizer \
              --prefix PYTHONPATH ":" "${pythonPackages.makePythonPath propagatedBuildInputs}:$out/share/${pname}" \
              --prefix PATH ":" "${pkgs.python3}/bin"

            mkdir -p $out/share/bash-completion/completions
            register-python-argcomplete ${pname} > $out/share/bash-completion/completions/${pname}

            mkdir -p $out/share/zsh/site-functions
            register-python-argcomplete -s zsh ${pname} > $out/share/zsh/site-functions/_${pname}

            runHook postInstall
          '';
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [
            (pkgs.python3.withPackages (ps: with ps; [ pillow argcomplete black ]))
            pkgs.sqlite
            pkgs.imagemagick
            pkgs.git
          ];

          shellHook = ''
            echo "Python dev environment ready"
            echo "try:  python3 hyprpaper-randomizer.py (run the app)"
            eval "$(register-python-argcomplete hyprpaper-randomizer.py)"
          '';
        };
      });
}

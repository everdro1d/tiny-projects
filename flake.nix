{
  description = "Nix flake for hyprmon-templates";

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
          pname = "hyprmon-templates";
          version = "1.0.0";
          src = ./.;
          format = "other";

          propagatedBuildInputs = with pythonPackages; [
            python
            argcomplete
            pkgs.makeWrapper
          ];

          nativeBuildInputs = [ pkgs.makeWrapper pythonPackages.argcomplete ];

          installPhase = ''
            runHook preInstall

            mkdir -p $out/share/${pname}
            cp -r . $out/share/${pname}/
            chmod +x $out/share/${pname}/hyprmon-templates.py

            mkdir -p $out/bin

            cp -s $out/share/${pname}/hyprmon-templates.py $out/bin/hyprmon-templates

            wrapProgram $out/bin/hyprmon-templates \
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
            (pkgs.python3.withPackages (ps: with ps; [ argcomplete ]))
            pkgs.git
          ];

          shellHook = ''
            echo "Python dev environment ready"
            echo "try:  python3 hyprmon-templates.py (run the app)"
            eval "$(register-python-argcomplete hyprmon-templates.py)"
          '';
        };
      });
}

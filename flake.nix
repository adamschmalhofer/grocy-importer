{
  description = "development environment for Grocy-Importer";

  # Flake inputs
  inputs = {
    nixpkgs.url = "https://flakehub.com/f/NixOS/nixpkgs/0.2305.491812.tar.gz";
  };

  # Flake outputs
  outputs = { self, nixpkgs }:
    let
      # Systems supported
      allSystems = [
        "x86_64-linux" # 64-bit Intel/AMD Linux
        "aarch64-linux" # 64-bit ARM Linux
        "x86_64-darwin" # 64-bit Intel macOS
        "aarch64-darwin" # 64-bit ARM macOS
      ];

      # Helper to provide system-specific attributes
      forAllSystems = f: nixpkgs.lib.genAttrs allSystems (system: f {
        pkgs = import nixpkgs { inherit system; };
      });
    in
    {
      # Development environment output
      devShells = forAllSystems ({ pkgs }: {
        default =
          let
            # Use Python 3.11
            python = pkgs.python311;
          in
          pkgs.mkShell {
            # The Nix packages provided in the environment
            packages = [
              (with pkgs; [
                # clitest          # not in nix
                docutils
                todo-txt-cli
              ])
              # Python plus helper tools
              (python.withPackages (ps: with ps; [
                tox
                mypy
                flake8
                beautifulsoup4
                requests
                # marshmallow      # not in nix
                appdirs
                argcomplete
                pdfminer-six
                html5lib
                recipe-scrapers
                pyyaml
              ]))
            ];
          };
      });
    };
}

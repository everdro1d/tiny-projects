# iPod Music Downloader

A downloader made to get the music files off of an old iPod Classic.

Copies the files from an iPod (tecnically anything really, just one dir to
another using metadata to rename and re-organize files).

Because the iPod obfuscates file names & locations, we get the metadata of
the original file and name the copied one according to `artist - title.ext`
Sorts the music into folders by genre only, because thats all I needed.

## To use:
  1. clone this repo
  2. mount the iPod
  3. run app.py with the input and output directories designated
     `python app.py -i /run/media/YOURUSER/IPOD/iPod_Control/Music -o ~/music/iPod/`

### Notes:
  * you can use -v or --verbose to enable logs in the console
  * missing artists & titles are logged into txt files with a list of paths
  * missing genres get put into `Unclassified` folder
  * if you use Nix, the flake in the repo has the devShell included so you
    can just use nix develop, run the app and be done with it
    `nix develop github:everdro1d/tiny-projects/ipod-music-downloader`

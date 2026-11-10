//! Locates the Steam Classic installation without asking the user.

use std::path::{Path, PathBuf};

const GAME_DIR: [&str; 3] = ["steamapps", "common", "Legacy of Kain Soul Reaver"];
const STEAM_ROOTS: [&str; 5] = [
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
    r"C:\SteamLibrary",
    r"D:\SteamLibrary",
    r"E:\SteamLibrary",
];

/// Library folders declared in Steam's `libraryfolders.vdf`.
///
/// Only the `"path"` entries matter, so a line scan is enough and avoids a
/// VDF parser: `"path" "D:\\SteamLibrary"`.
fn library_paths(vdf: &str) -> Vec<PathBuf> {
    vdf.lines()
        .filter_map(|line| {
            let mut quoted = line.split('"').skip(1).step_by(2);
            (quoted.next()? == "path").then(|| quoted.next())?
        })
        .filter(|path| !path.is_empty())
        .map(|path| PathBuf::from(path.replace(r"\\", r"\")))
        .collect()
}

fn has_game(library: &Path) -> Option<PathBuf> {
    let game = GAME_DIR
        .iter()
        .fold(library.to_path_buf(), |path, part| path.join(part));
    game.join("kain2.exe").is_file().then_some(game)
}

/// First Steam library that contains the game: libraries registered in Steam
/// first, then the conventional locations.
pub fn detect_game() -> Option<String> {
    let registered = STEAM_ROOTS.iter().flat_map(|root| {
        std::fs::read_to_string(Path::new(root).join("steamapps").join("libraryfolders.vdf"))
            .map(|vdf| library_paths(&vdf))
            .unwrap_or_default()
    });
    registered
        .chain(STEAM_ROOTS.iter().map(PathBuf::from))
        .find_map(|library| has_game(&library))
        .map(|game| game.to_string_lossy().into_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn library_paths_reads_every_declared_library_and_unescapes_separators() {
        let vdf = r#"
"libraryfolders"
{
	"0"
	{
		"path"		"C:\\Program Files (x86)\\Steam"
		"label"		""
		"apps"
		{
			"224920"		"1234"
		}
	}
	"1"
	{
		"path"		"F:\\Jogos\\SteamLibrary"
	}
	"2"
	{
		"path"		""
	}
}"#;
        assert_eq!(
            library_paths(vdf),
            vec![
                PathBuf::from(r"C:\Program Files (x86)\Steam"),
                PathBuf::from(r"F:\Jogos\SteamLibrary"),
            ]
        );
        assert!(library_paths("\"label\"\t\"path\"").is_empty());
    }

    #[test]
    fn a_library_counts_only_when_it_holds_the_executable() {
        let library = tempfile::tempdir().unwrap();
        assert_eq!(has_game(library.path()), None);
        let game = GAME_DIR
            .iter()
            .fold(library.path().to_path_buf(), |path, part| path.join(part));
        std::fs::create_dir_all(&game).unwrap();
        std::fs::write(game.join("kain2.exe"), b"fixture").unwrap();
        assert_eq!(has_game(library.path()), Some(game));
    }
}

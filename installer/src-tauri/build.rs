fn main() {
    println!("cargo:rerun-if-changed=../../tools/controller/bridge.cpp");
    println!("cargo:rerun-if-changed=../../tools/controller/build.cmd");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        let root =
            std::path::PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").unwrap()).join("../..");
        let output = std::env::var_os("OUT_DIR").unwrap();
        let result = std::process::Command::new("cmd")
            .arg("/C")
            .arg(root.join("tools/controller/build.cmd"))
            .arg(output)
            .current_dir(&root)
            .status()
            .expect("Não foi possível compilar o acompanhante DualSense");
        assert!(result.success(), "Build do acompanhante DualSense falhou");
    }
    tauri_build::build();
}

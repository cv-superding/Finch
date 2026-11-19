fn main() {
    // gnu_target_dir_fix: tauri-build 在 *-windows-gnu 下会扫描
    // <target>/<profile>/build/build 找 WebView2Loader.dll；新工程里该目录
    // 可能尚未生成，read_dir 会以 os error 3 失败。这里先建好。
    if let Ok(out_dir) = std::env::var("OUT_DIR") {
        let mut dir = std::path::PathBuf::from(out_dir);
        for _ in 0..3 {
            dir.pop();
        }
        let _ = std::fs::create_dir_all(dir.join("build"));
    }
    let conf = std::fs::read_to_string("tauri.conf.json").expect("read tauri.conf.json");
    let parsed: serde_json::Value = serde_json::from_str(&conf).expect("parse tauri.conf.json");
    let version = parsed["version"]
        .as_str()
        .expect("tauri.conf.json must have a \"version\" string field");
    println!("cargo:rustc-env=TAURI_CONF_VERSION={version}");
    println!("cargo:rerun-if-changed=tauri.conf.json");

    tauri_build::build()
}

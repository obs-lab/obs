use std::net::TcpStream;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct BackendProcess(Mutex<Option<CommandChild>>);

fn wait_for_backend(host: &str, port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    let address = format!("{}:{}", host, port);
    while Instant::now() < deadline {
        if TcpStream::connect(&address).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            let resource_dir = app.path().resource_dir()?;
            let candidates = [
                resource_dir.join("obs-backend").join("obs-backend"),
                resource_dir
                    .join("_up_")
                    .join("backend")
                    .join("dist")
                    .join("obs-backend")
                    .join("obs-backend"),
                resource_dir
                    .join("..")
                    .join("backend")
                    .join("dist")
                    .join("obs-backend")
                    .join("obs-backend"),
                resource_dir
                    .join("backend")
                    .join("dist")
                    .join("obs-backend")
                    .join("obs-backend"),
            ];
            let mut backend_exe = candidates[0].clone();
            for c in candidates.iter() {
                if c.exists() {
                    backend_exe = c.clone();
                    break;
                }
            }
            log::info!("backend executable: {}", backend_exe.to_string_lossy());

            let data_dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&data_dir).ok();

            let shell = app.shell();
            let (mut rx, child) = shell
                .command(backend_exe.to_string_lossy().to_string())
                .env("OBS_DATA_DIR", data_dir.to_string_lossy().to_string())
                .spawn()?;

            let state: State<BackendProcess> = app.state();
            *state.0.lock().unwrap() = Some(child);

            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stderr(line) => {
                            log::info!("{}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stdout(line) => {
                            log::info!("{}", String::from_utf8_lossy(&line));
                        }
                        _ => {}
                    }
                }
            });

            let ready = wait_for_backend("127.0.0.1", 8000, Duration::from_secs(90));
            let window = app.get_webview_window("main").unwrap();
            if ready {
                window.eval("window.location.replace('http://127.0.0.1:8000/')").unwrap();
            } else {
                window
                    .eval("document.body.innerHTML = '<h2 style=\"font-family:sans-serif;padding:2rem\">Backend did not start in time.</h2>'")
                    .unwrap();
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                let state: State<BackendProcess> = app_handle.state();
                let child = state.0.lock().unwrap().take();
                if let Some(child) = child {
                    let _ = child.kill();
                }
            }
        });
}

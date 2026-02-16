use actix_cors::Cors;
use actix_web::{web, App, HttpResponse, HttpServer, middleware};
use aes_gcm::{
    aead::{Aead, KeyInit, OsRng},
    Aes256Gcm, Nonce,
};
use base64::{engine::general_purpose::STANDARD as BASE64, Engine};
use rand::RngCore;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::Mutex;

// ── App state: holds per-channel encryption keys ──
struct AppState {
    keys: Mutex<HashMap<i64, Vec<u8>>>,
    master_secret: String,
}

// ── Request / Response types ──

#[derive(Deserialize)]
struct EncryptRequest {
    channel_id: i64,
    message: String,
}

#[derive(Serialize)]
struct EncryptResponse {
    encrypted: String,
}

#[derive(Deserialize)]
struct DecryptRequest {
    channel_id: i64,
    encrypted: String,
}

#[derive(Serialize)]
struct DecryptResponse {
    message: String,
}

#[derive(Serialize)]
struct ErrorResponse {
    error: String,
}

// ── Derive a per-channel 256-bit key from master secret + channel_id ──
fn derive_channel_key(master_secret: &str, channel_id: i64) -> Vec<u8> {
    let mut hasher = Sha256::new();
    hasher.update(master_secret.as_bytes());
    hasher.update(channel_id.to_le_bytes());
    hasher.finalize().to_vec()
}

// ── Get or create the key for a channel ──
fn get_or_create_key(state: &AppState, channel_id: i64) -> Vec<u8> {
    let mut keys = state.keys.lock().unwrap();
    keys.entry(channel_id)
        .or_insert_with(|| derive_channel_key(&state.master_secret, channel_id))
        .clone()
}

// ── POST /encrypt ──
async fn encrypt(
    data: web::Data<AppState>,
    body: web::Json<EncryptRequest>,
) -> HttpResponse {
    let key_bytes = get_or_create_key(&data, body.channel_id);

    let cipher = match Aes256Gcm::new_from_slice(&key_bytes) {
        Ok(c) => c,
        Err(e) => {
            log::error!("Failed to create cipher: {}", e);
            return HttpResponse::InternalServerError()
                .json(ErrorResponse { error: "Encryption init failed".into() });
        }
    };

    // Generate a random 12-byte nonce
    let mut nonce_bytes = [0u8; 12];
    OsRng.fill_bytes(&mut nonce_bytes);
    let nonce = Nonce::from_slice(&nonce_bytes);

    match cipher.encrypt(nonce, body.message.as_bytes()) {
        Ok(ciphertext) => {
            // Pack as: base64(nonce + ciphertext)
            let mut combined = nonce_bytes.to_vec();
            combined.extend_from_slice(&ciphertext);
            let encoded = BASE64.encode(&combined);

            log::info!("Encrypted message for channel {}", body.channel_id);
            HttpResponse::Ok().json(EncryptResponse { encrypted: encoded })
        }
        Err(e) => {
            log::error!("Encryption failed: {}", e);
            HttpResponse::InternalServerError()
                .json(ErrorResponse { error: "Encryption failed".into() })
        }
    }
}

// ── POST /decrypt ──
async fn decrypt(
    data: web::Data<AppState>,
    body: web::Json<DecryptRequest>,
) -> HttpResponse {
    let key_bytes = get_or_create_key(&data, body.channel_id);

    let cipher = match Aes256Gcm::new_from_slice(&key_bytes) {
        Ok(c) => c,
        Err(e) => {
            log::error!("Failed to create cipher: {}", e);
            return HttpResponse::InternalServerError()
                .json(ErrorResponse { error: "Decryption init failed".into() });
        }
    };

    let combined = match BASE64.decode(&body.encrypted) {
        Ok(d) => d,
        Err(e) => {
            log::error!("Base64 decode failed: {}", e);
            return HttpResponse::BadRequest()
                .json(ErrorResponse { error: "Invalid base64".into() });
        }
    };

    if combined.len() < 12 {
        return HttpResponse::BadRequest()
            .json(ErrorResponse { error: "Ciphertext too short".into() });
    }

    // Split nonce (first 12 bytes) from ciphertext
    let (nonce_bytes, ciphertext) = combined.split_at(12);
    let nonce = Nonce::from_slice(nonce_bytes);

    match cipher.decrypt(nonce, ciphertext) {
        Ok(plaintext) => {
            let message = String::from_utf8_lossy(&plaintext).to_string();
            log::info!("Decrypted message for channel {}", body.channel_id);
            HttpResponse::Ok().json(DecryptResponse { message })
        }
        Err(e) => {
            log::error!("Decryption failed: {}", e);
            HttpResponse::BadRequest()
                .json(ErrorResponse { error: "Decryption failed".into() })
        }
    }
}

// ── Health check ──
async fn health() -> HttpResponse {
    HttpResponse::Ok().json(serde_json::json!({"status": "ok"}))
}

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    dotenv::dotenv().ok();
    env_logger::init();

    let master_secret = std::env::var("MASTER_SECRET")
        .unwrap_or_else(|_| "default-secret-change-me".to_string());

    log::info!("Starting encryption service on port 8001");

    let state = web::Data::new(AppState {
        keys: Mutex::new(HashMap::new()),
        master_secret,
    });

    HttpServer::new(move || {
        let cors = Cors::permissive();

        App::new()
            .wrap(cors)
            .wrap(middleware::Logger::default())
            .app_data(state.clone())
            .route("/health", web::get().to(health))
            .route("/encrypt", web::post().to(encrypt))
            .route("/decrypt", web::post().to(decrypt))
    })
    .bind("127.0.0.1:8001")?
    .run()
    .await
}

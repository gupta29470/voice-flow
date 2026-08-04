from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    deepgram_api_key: str = ""
    kimi_api_key: str = ""
    cartesia_api_key: str = ""
    elevenlabs_api_key: str = ""

    public_url: str = "http://localhost:8000"

    frontend_url: str = "http://localhost:3000"
    database_path: str = "voiceflow.db"

    kimi_base_url: str = "https://api.kimi.com/coding/v1"
    kimi_model: str = "kimi-for-coding"
    deepgram_model: str = "nova-2-phonecall"
    cartesia_model: str = "sonic-3.5"
    elevenlabs_model: str = "eleven_flash_v2_5"

    human_handoff_number: str = "" 


settings = Settings()
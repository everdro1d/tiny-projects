package com.example.fortherepublic

import android.media.AudioAttributes
import android.media.SoundPool
import androidx.appcompat.app.AppCompatActivity
import android.os.Bundle
import android.widget.Button

class MainActivity : AppCompatActivity() {

    private lateinit var soundPool: SoundPool
    private var soundId: Int = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Initialize SoundPool
        val audioAttributes = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_GAME)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build()
        soundPool = SoundPool.Builder()
            .setMaxStreams(1)
            .setAudioAttributes(audioAttributes)
            .build()

        // Load sound file
        soundId = soundPool.load(this, R.raw.fortherepublic, 1)

        // Set click listener for the button
        val playButton = findViewById<Button>(R.id.playButton)
        playButton.setOnClickListener {
            soundPool.play(soundId, 1f, 1f, 0, 0, 1f)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        soundPool.release()
    }
}
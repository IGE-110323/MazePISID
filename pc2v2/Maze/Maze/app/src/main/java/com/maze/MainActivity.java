package com.maze;

import android.os.Bundle;
import android.view.MenuItem;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.fragment.app.Fragment;

import com.google.android.material.bottomnavigation.BottomNavigationView;

public class MainActivity extends AppCompatActivity {

    private String host;
    private String database;
    private String username;
    private String password;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        // Obter os dados passados da MazeLoginActivity
        host = getIntent().getStringExtra("host");
        database = getIntent().getStringExtra("database");
        username = getIntent().getStringExtra("username");
        password = getIntent().getStringExtra("password");
        // String idGrupo = getIntent().getStringExtra("IDGrupo");

        BottomNavigationView bottomNav = findViewById(R.id.bottom_navigation);
        bottomNav.setOnNavigationItemSelectedListener(navListener);

        // Carrega o fragment inicial
        if (savedInstanceState == null) {
            getSupportFragmentManager().beginTransaction()
                    .replace(R.id.fragment_container, MazeMessagesFragment.newInstance(host, database, username, password))
                    .commit();
        }
    }

    private BottomNavigationView.OnNavigationItemSelectedListener navListener =
            new BottomNavigationView.OnNavigationItemSelectedListener() {
                @Override
                public boolean onNavigationItemSelected(@NonNull MenuItem item) {
                    Fragment selectedFragment = null;

                    // O ID do item é o mesmo definido em @menu/bottom_navigation_menu.xml
                    int itemId = item.getItemId();
                    if (itemId == R.id.nav_messages) {
                        selectedFragment = MazeMessagesFragment.newInstance(host, database, username, password);
                    } else if (itemId == R.id.nav_room) {
                        selectedFragment = MarsamiRoomFragment.newInstance(host, database, username, password);
                    } else if (itemId == R.id.nav_sound) {
                        selectedFragment = MazeSoundFragment.newInstance(host, database, username, password);
                    } else if (itemId == R.id.nav_temperature) {
                        selectedFragment = MazeTemperatureFragment.newInstance(host, database, username, password);
                    }

                    if (selectedFragment != null) {
                        getSupportFragmentManager().beginTransaction()
                                .replace(R.id.fragment_container, selectedFragment)
                                .commit();
                    }
                    return true;
                }
            };
}
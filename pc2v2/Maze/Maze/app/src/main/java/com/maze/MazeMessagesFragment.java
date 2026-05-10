package com.maze;

import android.graphics.Color;
import android.os.Bundle;
import android.text.Spannable;
import android.text.SpannableStringBuilder;
import android.text.style.ForegroundColorSpan;
import android.util.Log;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import com.maze.models.Mensagem;
import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;

import java.io.IOException;
import java.lang.reflect.Type;
import java.net.URLEncoder; // Importar para codificação de URL
import java.util.List;

import okhttp3.Call;
import okhttp3.Callback;
import okhttp3.HttpUrl; // Importar para construir URL com parâmetros
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import org.json.JSONArray;
import org.json.JSONObject;
public class MazeMessagesFragment extends Fragment {

    private static final String ARG_HOST = "host";
    private static final String ARG_DATABASE = "database";
    private static final String ARG_USERNAME = "username";
    private static final String ARG_PASSWORD = "password";

    private String host;
    private String database;
    private String username;
    private String password;
    private TextView tvMessages;
    private OkHttpClient client;

    public MazeMessagesFragment() {
        // Required empty public constructor
    }

    public static MazeMessagesFragment newInstance(String host, String database, String username, String password) {
        MazeMessagesFragment fragment = new MazeMessagesFragment();
        Log.d("MazeActivity", "username: " + username);
        Log.d("MazeActivity", "password: " + password);
        Bundle args = new Bundle();
        args.putString(ARG_HOST, host);
        args.putString(ARG_DATABASE, database);
        args.putString(ARG_USERNAME, username);
        args.putString(ARG_PASSWORD, password);
        fragment.setArguments(args);
        return fragment;
    }

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (getArguments() != null) {
            host = getArguments().getString(ARG_HOST);
            database = getArguments().getString(ARG_DATABASE);
            username = getArguments().getString(ARG_USERNAME);
            password = getArguments().getString(ARG_PASSWORD);
        }
        client = new OkHttpClient();
    }

    @Override
    public View onCreateView(LayoutInflater inflater, ViewGroup container,
                             Bundle savedInstanceState) {
        View view = inflater.inflate(R.layout.fragment_maze_messages, container, false);
        tvMessages = view.findViewById(R.id.tvMessages);
        return view;
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);
        fetchMessages();
    }

    private void fetchMessages() {
        // ---- ALTERAÇÃO AQUI: Construir URL com parâmetros GET ----
        HttpUrl.Builder urlBuilder = HttpUrl.parse("http://" + host + "/maze_app_php/get_messages.php").newBuilder();
        urlBuilder.addQueryParameter("database", database);
        urlBuilder.addQueryParameter("username", username);
        urlBuilder.addQueryParameter("password", password);
        String messagesUrl = urlBuilder.build().toString();

        Log.d("MazeMessages", "GET URL: " + messagesUrl); // Para ver a URL no Logcat

        Request request = new Request.Builder()
                .url(messagesUrl)
                .get()
                .build();

        client.newCall(request).enqueue(new Callback() {
            @Override
            public void onFailure(@NonNull Call call, @NonNull IOException e) {
                if (getActivity() != null) {
                    getActivity().runOnUiThread(() -> Toast.makeText(getContext(), "Erro de conexão: " + e.getMessage(), Toast.LENGTH_LONG).show());
                }

            }

            @Override
            public void onResponse(@NonNull Call call, @NonNull Response response) throws IOException {
                Log.d("MazeActivity", "Response: " + response); // Mudado para Log.d para ver respostas bem-sucedidas também
                if (response.isSuccessful() && response.body() != null) {
                    String responseData = response.body().string();


                    try {
                        JSONObject jsonResponse = new JSONObject(responseData);
                        String responseData2 = jsonResponse.getJSONArray("data").toString();
                        Gson gson = new Gson();
                        Type listType = new TypeToken<List<Mensagem>>(){}.getType();
                        List<Mensagem> messages = gson.fromJson(responseData2, listType);
                        if (getActivity() != null) {
                            getActivity().runOnUiThread(() -> displayMessages(messages));
                        }
                    } catch (Exception e) {
                        Log.e("MazeMessages", "Erro ao parsear JSON: " + e.getMessage());
                        if (getActivity() != null) {
                            getActivity().runOnUiThread(() -> Toast.makeText(getContext(), "Erro no formato da resposta das mensagens.", Toast.LENGTH_LONG).show());
                        }
                    }
                } else {
                    // Adicionar log para respostas não bem-sucedidas do servidor
                    String errorBody = response.body() != null ? response.body().string() : "No error body";
                    if (getActivity() != null) {
                        getActivity().runOnUiThread(() -> Toast.makeText(getContext(), "Erro do servidor: " + response.code(), Toast.LENGTH_LONG).show());
                    }
                }
            }
        });
    }

    private void displayMessages(List<Mensagem> messages) {
        SpannableStringBuilder ssb = new SpannableStringBuilder();
        if (messages == null || messages.isEmpty()) {
            ssb.append("Nenhuma mensagem encontrada.");
            tvMessages.setText(ssb);
            return;
        }

        for (Mensagem msg : messages) {
            String line = "Data: " + msg.getDate() + " | Texto: " + msg.getText() +
                    " | Valor: " + msg.getValue() + " | Tipo: " + msg.getMessagetype() +
                    " | Id: " + msg.getId() + " | Sensor: " + msg.getSensor() + "\n";

            int color = Color.WHITE; // Cor padrão
            switch (msg.getMessagetype()) {
                case 1:
                    color = Color.BLUE;
                    break;
                case 2:
                    color = Color.GREEN;
                    break;
                case 3:
                    color = Color.RED;
                    break;
                //....adicionar
            }

            int start = ssb.length();
            ssb.append(line);
            int end = ssb.length();
            ssb.setSpan(new ForegroundColorSpan(color), start, end, Spannable.SPAN_EXCLUSIVE_EXCLUSIVE);
        }
        tvMessages.setText(ssb);
    }
}
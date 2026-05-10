package com.maze;

import android.annotation.SuppressLint;
import android.graphics.Color;
import android.os.Bundle;
import android.util.Log;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import com.github.mikephil.charting.charts.BarChart;
import com.github.mikephil.charting.components.XAxis;
import com.github.mikephil.charting.data.BarData;
import com.github.mikephil.charting.data.BarDataSet;
import com.github.mikephil.charting.data.BarEntry;
import com.github.mikephil.charting.formatter.IndexAxisValueFormatter;
import com.github.mikephil.charting.interfaces.datasets.IBarDataSet;
import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;
import com.maze.models.RoomData; // Importe a sua nova classe RoomData

import org.json.JSONObject;

import java.io.IOException;
import java.lang.reflect.Type;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.List;

import okhttp3.Call;
import okhttp3.Callback;
import okhttp3.HttpUrl;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;

public class MarsamiRoomFragment extends Fragment {

    private static final String ARG_HOST = "host";
    private static final String ARG_DATABASE = "database";
    private static final String ARG_USERNAME = "username";
    private static final String ARG_PASSWORD = "password";

    private String host;
    private String database;
    private String username;
    private String password;

    private BarChart barChart;
    private OkHttpClient client;

    public MarsamiRoomFragment() {
        // Required empty public constructor
    }

    public static MarsamiRoomFragment newInstance(String host, String database, String username, String password) {
        MarsamiRoomFragment fragment = new MarsamiRoomFragment();
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

    @SuppressLint("MissingInflatedId")
    @Override
    public View onCreateView(LayoutInflater inflater, ViewGroup container,
                             Bundle savedInstanceState) {
        View view = inflater.inflate(R.layout.fragment_marsami_room, container, false);
        barChart = view.findViewById(R.id.barChart); // Assuma que você tem um BarChart com este ID no seu XML
        setupChart();
        return view;
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);
        fetchRoomData();
    }

    private void setupChart() {
        barChart.getDescription().setEnabled(false); // Remove a descrição padrão
        barChart.setPinchZoom(false); // Desativa zoom com pinça
        barChart.setDrawBarShadow(false); // Não desenha sombra nas barras
        barChart.setDrawGridBackground(false); // Não desenha fundo da grade

        // Eixo X
        XAxis xAxis = barChart.getXAxis();
        xAxis.setPosition(XAxis.XAxisPosition.BOTTOM);
        xAxis.setDrawGridLines(false);
        xAxis.setDrawAxisLine(true);
        xAxis.setGranularity(1f); // Garante que as labels são mostradas para cada grupo
        xAxis.setGranularityEnabled(true);
        xAxis.setCenterAxisLabels(true); // Centraliza a label da sala para o grupo de barras

        // Eixo Y (esquerda)
        barChart.getAxisLeft().setDrawGridLines(true);
        barChart.getAxisLeft().setAxisMinimum(0f); // Começa em 0
        barChart.getAxisLeft().setGranularity(1f); // Define a granularidade do eixo Y para inteiros

        // Eixo Y (direita) - desativado para simplicidade
        barChart.getAxisRight().setEnabled(false);

        barChart.setFitBars(true); // Ajusta as barras ao tamanho
        barChart.animateY(1500); // Animação
        barChart.setNoDataText("A carregar dados..."); // Texto quando não há dados
    }

    private void fetchRoomData() {
        String roomDataUrl = "http://" + host + "/maze_app_php/get_room_data.php"; // Ajuste o nome do seu script PHP se for diferente

        HttpUrl.Builder urlBuilder = HttpUrl.parse(roomDataUrl).newBuilder();
        try {
            urlBuilder.addQueryParameter("database", database);
            urlBuilder.addQueryParameter("username", username);
            urlBuilder.addQueryParameter("password", password);
        } catch (Exception e) {
            Log.e("MarsamiRoomFragment", "Erro ao codificar parâmetros URL: " + e.getMessage());
            if (getActivity() != null) {
                getActivity().runOnUiThread(() -> Toast.makeText(getContext(), "Erro ao preparar requisição.", Toast.LENGTH_LONG).show());
            }
            return;
        }

        String finalUrl = urlBuilder.build().toString();
        Log.d("MarsamiRoomFragment", "GET URL (Rooms): " + finalUrl);

        Request request = new Request.Builder()
                .url(finalUrl)
                .get()
                .build();

        client.newCall(request).enqueue(new Callback() {
            @Override
            public void onFailure(@NonNull Call call, @NonNull IOException e) {
                if (getActivity() != null) {
                    getActivity().runOnUiThread(() -> Toast.makeText(getContext(), "Erro de conexão ao buscar dados dos quartos: " + e.getMessage(), Toast.LENGTH_LONG).show());
                }
                Log.e("MarsamiRoomFragment", "Erro na requisição dos quartos: " + e.getMessage());
            }

            @Override
            public void onResponse(@NonNull Call call, @NonNull Response response) throws IOException {
                if (response.isSuccessful() && response.body() != null) {
                    String responseData = response.body().string();
                    Log.d("MarsamiRoomFragment", "Resposta do PHP (Rooms): " + responseData);
                    try {
                        JSONObject jsonResponse = new JSONObject(responseData);
                        String responseData2 = jsonResponse.getJSONArray("data").toString();
                        Gson gson = new Gson();
                        Type listType = new TypeToken<List<RoomData>>(){}.getType();
                        List<RoomData> roomDataList = gson.fromJson(responseData2, listType);

                        if (getActivity() != null) {
                            getActivity().runOnUiThread(() -> updateChart(roomDataList));
                        }
                    } catch (Exception e) {
                        Log.e("MarsamiRoomFragment", "Erro ao parsear JSON dos quartos: " + e.getMessage());
                        if (getActivity() != null) {
                            getActivity().runOnUiThread(() -> Toast.makeText(getContext(), "Erro no formato da resposta dos quartos.", Toast.LENGTH_LONG).show());
                        }
                    }
                } else {
                    String errorBody = response.body() != null ? response.body().string() : "No error body";
                    Log.e("MarsamiRoomFragment", "Erro do servidor ao buscar dados dos quartos: " + response.code() + " - " + errorBody);
                    if (getActivity() != null) {
                        getActivity().runOnUiThread(() -> Toast.makeText(getContext(), "Erro do servidor ao buscar dados dos quartos: " + response.code(), Toast.LENGTH_LONG).show());
                    }
                }
            }
        });
    }

    private void updateChart(List<RoomData> roomDataList) {
        if (roomDataList == null || roomDataList.isEmpty()) {
            barChart.clear();
            barChart.invalidate();
            barChart.setNoDataText("Nenhum dado de quarto encontrado para exibir.");
            return;
        }

        ArrayList<BarEntry> entriesEven = new ArrayList<>();
        ArrayList<BarEntry> entriesOdd = new ArrayList<>();
        ArrayList<String> roomLabels = new ArrayList<>();

        for (int i = 0; i < roomDataList.size(); i++) {
            RoomData room = roomDataList.get(i);
            float x = i; // O índice da sala no eixo X

            float evenValue = 0f;
            try {
                evenValue = Float.parseFloat(room.getNumberEven());
            } catch (NumberFormatException e) {
                Log.e("MarsamiRoomFragment", "Erro ao converter numberEven para float na Sala " + room.getRoom() + ": " + room.getNumberEven());

            }

            float oddValue = 0f;
            try {
                oddValue = Float.parseFloat(room.getNumberOdd());
            } catch (NumberFormatException e) {
                Log.e("MarsamiRoomFragment", "Erro ao converter numberOdd para float na Sala " + room.getRoom() + ": " + room.getNumberOdd());

            }

            entriesEven.add(new BarEntry(x, evenValue));
            entriesOdd.add(new BarEntry(x, oddValue));
            roomLabels.add("Sala " + room.getRoom()); // Labels para o eixo X
        }

        BarDataSet setEven = new BarDataSet(entriesEven, "Nº Par");
        setEven.setColor(Color.BLUE);
        setEven.setDrawValues(true);

        BarDataSet setOdd = new BarDataSet(entriesOdd, "Nº Ímpar");
        setOdd.setColor(Color.RED);
        setOdd.setDrawValues(true);

        ArrayList<IBarDataSet> dataSets = new ArrayList<>();
        dataSets.add(setEven);
        dataSets.add(setOdd);

        BarData barData = new BarData(dataSets);

        // --- Configurações para Agrupamento ---
        // Estes valores controlam o espaçamento e a largura das barras agrupadas
        float groupSpace = 0.08f;
        float barSpace = 0.02f; // x2 dataset (0.02f de espaço entre as 2 barras do mesmo grupo)
        float barWidth = 0.44f; // x2 dataset (0.44f de largura para cada uma das 2 barras)

        // IMPORTANTE: (barWidth + barSpace) * number_of_datasets + groupSpace = 1.0 (ou próximo de 1.0)
        // Para 2 datasets: (0.44 + 0.02) * 2 + 0.08 = 0.46 * 2 + 0.08 = 0.92 + 0.08 = 1.0
        barData.setBarWidth(barWidth);

        // Ajustar o mínimo e máximo do eixo X para que as labels fiquem centralizadas e todas as barras visíveis
        float startX = 0f; // Ponto de partida do primeiro grupo
        barChart.getXAxis().setAxisMinimum(startX);
        // O maximo deve ser o startX + (número de grupos * largura total de um grupo)
        barChart.getXAxis().setAxisMaximum(startX + barData.getGroupWidth(groupSpace, barSpace) * roomDataList.size());


        // Chamar groupBars com o offset correto
        barData.groupBars(startX, groupSpace, barSpace);

        // Configurar o eixo X novamente após o agrupamento
        XAxis xAxis = barChart.getXAxis();
        xAxis.setValueFormatter(new IndexAxisValueFormatter(roomLabels));
        xAxis.setLabelCount(roomLabels.size(), false); // Força a exibição de todas as labels

        barChart.setData(barData);
        barChart.invalidate(); // Redesenha o gráfico
    }
}
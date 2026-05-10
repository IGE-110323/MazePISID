package com.maze;

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

import com.github.mikephil.charting.charts.LineChart;
import com.github.mikephil.charting.components.Legend;
import com.github.mikephil.charting.components.XAxis;
import com.github.mikephil.charting.components.YAxis;
import com.github.mikephil.charting.data.Entry;
import com.github.mikephil.charting.data.LineData;
import com.github.mikephil.charting.data.LineDataSet;
import com.github.mikephil.charting.interfaces.datasets.ILineDataSet;
import com.maze.models.HighValue;
import com.maze.models.SoundData;
import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;

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
import org.json.JSONArray;
public class MazeSoundFragment extends Fragment {

    private static final String ARG_HOST = "host";
    private static final String ARG_DATABASE = "database";
    private static final String ARG_USERNAME = "username";
    private static final String ARG_PASSWORD = "password";

    private String host;
    private String database;
    private String username;
    private String password;
    private LineChart lineChart;
    private OkHttpClient client;

    public MazeSoundFragment() {
        // Required empty public constructor
    }

    public static MazeSoundFragment newInstance(String host, String database, String username, String password) {
        MazeSoundFragment fragment = new MazeSoundFragment();
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
        View view = inflater.inflate(R.layout.fragment_maze_sound, container, false);
        lineChart = view.findViewById(R.id.lineChartSound);
        return view;
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);
        setupChart();
        fetchSoundData();
    }

    private void setupChart() {
        lineChart.getDescription().setEnabled(false);
        lineChart.setTouchEnabled(true);
        lineChart.setDragEnabled(true);
        lineChart.setScaleEnabled(true);
        lineChart.setPinchZoom(true);

        XAxis xAxis = lineChart.getXAxis();
        xAxis.setPosition(XAxis.XAxisPosition.BOTTOM);
        xAxis.setDrawGridLines(false);
        xAxis.setGranularity(1f);

        YAxis leftAxis = lineChart.getAxisLeft();
        leftAxis.setAxisMinimum(0f);
        lineChart.getAxisRight().setEnabled(false);

        Legend legend = lineChart.getLegend();
        legend.setForm(Legend.LegendForm.LINE);
        legend.setTextSize(12f);
    }

    private void fetchSoundData() {
        String soundUrl = "http://" + host + "/maze_app_php/get_sound_data.php";

        HttpUrl.Builder urlBuilder = HttpUrl.parse(soundUrl).newBuilder();
        try {
            urlBuilder.addQueryParameter("database", URLEncoder.encode(database, "UTF-8"));
            urlBuilder.addQueryParameter("username", username);
            urlBuilder.addQueryParameter("password", URLEncoder.encode(password, "UTF-8"));
        } catch (Exception e) {
            Log.e("MazeSound", "Erro ao codificar parâmetros URL para sound data: " + e.getMessage());
            if (getActivity() != null) {
                getActivity().runOnUiThread(() -> Toast.makeText(getContext(), "Erro ao preparar requisição de som.", Toast.LENGTH_LONG).show());
            }
            return;
        }
        String finalUrl = urlBuilder.build().toString();
        Log.d("MazeSound", "GET URL (Sound Data): " + finalUrl);
        Request request = new Request.Builder()
                .url(finalUrl)
                .get()
                .build();

        client.newCall(request).enqueue(new Callback() {
            @Override
            public void onFailure(@NonNull Call call, @NonNull IOException e) {
                if (getActivity() != null) {
                    getActivity().runOnUiThread(() -> Toast.makeText(getContext(), "Erro de conexão ao buscar dados de som: " + e.getMessage(), Toast.LENGTH_LONG).show());
                }
                Log.e("MazeSound", "Erro na requisição de som: " + e.getMessage());
            }


            @Override
            public void onResponse(@NonNull Call call, @NonNull Response response) throws IOException {
                if (response.isSuccessful() && response.body() != null) {
                    String responseData = response.body().string();

                    try {
                        Log.d("DEBUG_MAZE", "JSON Recebido: " + responseData);
                        JSONObject jsonResponse = new JSONObject(responseData);

                        // 1. Verificar se o PHP reportou sucesso
                        if (jsonResponse.optBoolean("success")) {

                            // 2. Extrair o Array "data" (onde estão os pontos do som)
                            // O erro acontecia aqui quando o PHP mandava um erro ou objeto simples
                            JSONArray dataArray = jsonResponse.getJSONArray("data");
                            String jsonListaSons = dataArray.toString();

                            Gson gson = new Gson();
                            Type soundListType = new TypeToken<List<SoundData>>(){}.getType();
                            List<SoundData> soundDataList = gson.fromJson(jsonListaSons, soundListType);

                            // 3. Validar a lista e avançar para o HighValue
                            if (soundDataList != null && !soundDataList.isEmpty()) {
                                Log.d("DEBUG_MAZE", "Sons carregados: " + soundDataList.size());
                                fetchHighValue(soundDataList);
                            } else {
                                Log.w("MazeSound", "Lista de sons vazia.");
                                if (getActivity() != null) {
                                    getActivity().runOnUiThread(() ->
                                            Toast.makeText(getContext(), "Nenhum dado de som encontrado.", Toast.LENGTH_SHORT).show());
                                }
                            }
                        } else {
                            // Se success for false, lemos a mensagem de erro do PHP
                            String msgErro = jsonResponse.optString("message", "Erro desconhecido no servidor");
                            Log.e("MazeSound", "Erro PHP: " + msgErro);
                            if (getActivity() != null) {
                                getActivity().runOnUiThread(() ->
                                        Toast.makeText(getContext(), msgErro, Toast.LENGTH_LONG).show());
                            }
                        }
                    } catch (Exception e) {
                        Log.e("MazeSound", "Erro ao parsear JSON: " + e.getMessage());
                        if (getActivity() != null) {
                            getActivity().runOnUiThread(() ->
                                    Toast.makeText(getContext(), "Erro no processamento dos dados.", Toast.LENGTH_SHORT).show());
                        }
                    }
                } else {
                    String errorBody = response.body() != null ? response.body().string() : "No body";
                    Log.e("MazeSound", "Erro " + response.code() + ": " + errorBody);
                    if (getActivity() != null) {
                        getActivity().runOnUiThread(() ->
                                Toast.makeText(getContext(), "Erro do servidor: " + response.code(), Toast.LENGTH_SHORT).show());
                    }
                }
            }
        });
    }

    private void fetchHighValue(List<SoundData> soundDataList) {
        String highValueUrl = "http://" + host + "/maze_app_php/get_max_sound_value.php";

        HttpUrl.Builder urlBuilder = HttpUrl.parse(highValueUrl).newBuilder();
        try {
            urlBuilder.addQueryParameter("database", database); // Removi o encode aqui pois o HttpUrlBuilder já trata disso
            urlBuilder.addQueryParameter("username", username);
            urlBuilder.addQueryParameter("password", password);
        } catch (Exception e) {
            Log.e("MazeSound", "Erro ao preparar URL: " + e.getMessage());
            return;
        }

        String finalUrl = urlBuilder.build().toString();
        Request request = new Request.Builder().url(finalUrl).get().build();

        client.newCall(request).enqueue(new Callback() {
            @Override
            public void onFailure(@NonNull Call call, @NonNull IOException e) {
                Log.e("MazeSound", "Falha HighValue: " + e.getMessage());
            }

            @Override
            public void onResponse(@NonNull Call call, @NonNull Response response) throws IOException {
                if (response.isSuccessful() && response.body() != null) {
                    String responseData = response.body().string();
                    try {
                        JSONObject jsonResponse = new JSONObject(responseData);

                        if (jsonResponse.optBoolean("success")) {
                            // --- CORREÇÃO AQUI ---
                            // 'data' é um JSONObject {"maximo":"20"}, NÃO um JSONArray
                            JSONObject dataObj = jsonResponse.getJSONObject("data");

                            // Extraímos o valor diretamente do objeto
                            // Se no PHP a chave for "maximo", usamos "maximo"
                            float maxHighValue = (float) dataObj.optDouble("maximo", 0.0);

                            if (getActivity() != null) {
                                getActivity().runOnUiThread(() -> updateChart(soundDataList, maxHighValue));
                            }
                        } else {
                            Log.e("MazeSound", "PHP Erro: " + jsonResponse.optString("message"));
                        }
                    } catch (Exception e) {
                        Log.e("MazeSound", "Erro ao parsear HighValue: " + e.getMessage());
                    }
                }
            }
        });
    }


    private void updateChart(List<SoundData> soundDataList, float maxHighValue) {
        lineChart.clear();
        lineChart.invalidate();

        Log.d("MazeSound", "--- Updating Sound Chart ---");
        Log.d("MazeSound", "soundDataList size: " + (soundDataList != null ? soundDataList.size() : "null"));
        Log.d("MazeSound", "maxHighValue for chart: " + maxHighValue);

        if (soundDataList == null || soundDataList.isEmpty()) {
            lineChart.setNoDataText("Nenhum dado de som encontrado para exibir.");
            lineChart.invalidate();
            Log.w("MazeSound", "soundDataList é nula ou vazia. Gráfico não desenhado.");
            return;
        }

        ArrayList<Entry> soundEntries = new ArrayList<>();
        ArrayList<Entry> maxLineEntries = new ArrayList<>();

        // Calculate min/max X and Y values from your sound data
        float minXData = Float.MAX_VALUE;
        float maxXData = Float.MIN_VALUE;
        float minYData = Float.MAX_VALUE;
        float maxYData = Float.MIN_VALUE;

        for (SoundData data : soundDataList) {
            if (data == null) {
                Log.w("MazeSound", "SoundData object is null, skipping entry.");
                continue;
            }

            float id = (float) data.getId();
            float value = data.getValue();


            if (Float.isNaN(id) || Float.isInfinite(id) || Float.isNaN(value) || Float.isInfinite(value)) {
                Log.e("MazeSound", "Invalid ID or Value found for Entry. Skipping: ID=" + id + ", Value=" + value);
                continue;
            }

            soundEntries.add(new Entry(id, value));
            maxLineEntries.add(new Entry(id, maxHighValue)); // maxHighValue é constante

            // Update min/max for axis auto-scaling
            if (id < minXData) minXData = id;
            if (id > maxXData) maxXData = id;
            if (value < minYData) minYData = value;
            if (value > maxYData) maxYData = value;
        }

        Log.d("MazeSound", "Total soundEntries created: " + soundEntries.size());

        if (soundEntries.isEmpty()) {
            lineChart.setNoDataText("Erro: Dados de som inválidos para exibir após processamento.");
            lineChart.invalidate();
            Log.e("MazeSound", "soundEntries está vazia após o loop de processamento. Nenhum dado válido encontrado.");
            return;
        }

        LineDataSet soundDataSet = new LineDataSet(soundEntries, "Sound Value");
        soundDataSet.setColor(Color.BLUE);
        soundDataSet.setDrawCircles(true);
        soundDataSet.setDrawValues(false);
        soundDataSet.setLineWidth(2f);
        soundDataSet.setMode(LineDataSet.Mode.CUBIC_BEZIER);

        LineDataSet maxLineDataSet = new LineDataSet(maxLineEntries, "Max High Value");
        maxLineDataSet.setColor(Color.RED);
        maxLineDataSet.setDrawCircles(false);
        maxLineDataSet.setDrawValues(false);
        maxLineDataSet.setLineWidth(2f);
        maxLineDataSet.enableDashedLine(10f, 5f, 0f);

        ArrayList<ILineDataSet> dataSets = new ArrayList<>();
        dataSets.add(soundDataSet);
        dataSets.add(maxLineDataSet);

        LineData lineData = new LineData(dataSets);
        lineChart.setData(lineData);

        // --- CÓDIGO CRÍTICO PARA OS EIXOS ---
        YAxis leftAxis = lineChart.getAxisLeft();
        // Use Math.min para garantir que o mínimo do eixo Y não seja maior que o máximo
        // E adicione um pouco de margem
        leftAxis.setAxisMinimum(Math.min(minYData, 0f) - 1f); // Garante que o mínimo é sensato
        leftAxis.setAxisMaximum(Math.max(maxYData, maxHighValue) + 1f); // Garante que o máximo é sensato
        leftAxis.setGranularity(1f); // Adicionar para evitar problemas de escala automática

        XAxis xAxis = lineChart.getXAxis();
        // Use Math.min para garantir que o mínimo do eixo X não seja maior que o máximo
        // E adicione um pouco de margem
        xAxis.setAxisMinimum(minXData - 0.5f);
        xAxis.setAxisMaximum(maxXData + 0.5f);
        xAxis.setGranularity(1f); // Importantíssimo para XAxis, especialmente com IDs inteiros

        Log.d("MazeSound", "Chart Axis Y Range: " + leftAxis.getAxisMinimum() + " to " + leftAxis.getAxisMaximum());
        Log.d("MazeSound", "Chart Axis X Range: " + xAxis.getAxisMinimum() + " to " + xAxis.getAxisMaximum());

        // Se o gráfico não estiver a aparecer, tente estas linhas adicionais para o viewPort
        // lineChart.setVisibleXRangeMaximum(10f); // Mostra no máximo 10 entradas de cada vez
        // lineChart.moveViewToX(lineChart.getXAxis().getAxisMaximum()); // Move a view para o final dos dados

        lineChart.invalidate(); // Force redraw
        Log.d("MazeSound", "Chart invalidated for redraw.");
    }
}
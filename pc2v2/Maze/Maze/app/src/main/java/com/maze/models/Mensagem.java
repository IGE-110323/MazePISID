package com.maze.models;

import com.google.gson.annotations.SerializedName;

public class Mensagem {
    @SerializedName("id")
    private String id;

    @SerializedName("tipoalerta")
    private String tipoalerta; // O PHP envia "S", por isso usamos String

    @SerializedName("hora")
    private String date;

    @SerializedName("msg")
    private String text;

    @SerializedName("leitura")
    private String value;

    @SerializedName("sensor")
    private String sensor;

    // Construtor vazio necessário para o GSON
    public Mensagem() {}

    // Getters
    public String getId() { return id; }
    public String getDate() { return date; }
    public String getText() { return text; }
    public String getValue() { return value; }
    public String getSensor() { return sensor; }

    // No seu Fragment, você usa getMessagetype(). Vamos adaptar:
    public int getMessagetype() {
        // Se tipoalerta for "S", "A", etc., precisamos converter para int para o seu switch
        if (tipoalerta == null) return 0;
        if (tipoalerta.equals("S")) return 1;
        return 0;
    }
}
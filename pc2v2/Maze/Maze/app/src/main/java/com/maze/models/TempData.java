package com.maze.models;

import com.google.gson.annotations.SerializedName;

public class TempData {

    // Deve coincidir com 'idtemperatura' do seu SELECT
    @SerializedName("idtemperatura")
    private int id;

    // Deve coincidir com 'temperatura' do seu SELECT
    @SerializedName("temperatura")
    private float value;

    // Construtor vazio (necessário para o GSON)
    public TempData() {
    }

    public TempData(int id, float value) {
        this.id = id;
        this.value = value;
    }

    // Getters
    public int getID() {
        return id;
    }

    public float getValue() {
        return value;
    }

    // Setters (opcional, mas recomendado)
    public void setID(int id) {
        this.id = id;
    }

    public void setValue(float value) {
        this.value = value;
    }
}

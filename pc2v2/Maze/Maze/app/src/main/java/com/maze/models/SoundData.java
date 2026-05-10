package com.maze.models;

import com.google.gson.annotations.SerializedName;

public class SoundData {

    // Deve coincidir com 'idsom' do seu SELECT
    @SerializedName("idsom")
    private int id;

    // Deve coincidir com 'som' do seu SELECT
    @SerializedName("som")
    private float value;

    // Construtor vazio (importante para o GSON)
    public SoundData() {
    }

    public SoundData(int id, float value) {
        this.id = id;
        this.value = value;
    }

    // Getters
    public int getId() {
        return id;
    }

    public float getValue() {
        return value;
    }

    // Setters
    public void setId(int id) {
        this.id = id;
    }

    public void setValue(float value) {
        this.value = value;
    }
}
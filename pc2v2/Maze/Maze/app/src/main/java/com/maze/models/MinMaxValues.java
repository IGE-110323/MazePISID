// com.maze.models.MinMaxValues.java
package com.maze.models;

import com.google.gson.annotations.SerializedName;

public class MinMaxValues {

    @SerializedName("minimo")
    private float minimo;
    @SerializedName("maximo")
    private float maximo;


    public MinMaxValues(float minimo, float maximo) {
        this.maximo = maximo;
        this.minimo = minimo;
    }

    public float getMaximo() {
        return maximo;
    }

    public float getMinimo() {
        return minimo;
    }
}
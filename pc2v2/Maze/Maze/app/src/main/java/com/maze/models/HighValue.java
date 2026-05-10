// com.maze.models.HighValue.java
package com.maze.models;

import com.google.gson.annotations.SerializedName;

public class HighValue {
    @SerializedName("maximo")
    private float maximo;


    public HighValue(float maximo) {
        this.maximo = maximo;
    }


    public float getMaximo() {
        return maximo;
    }


    public void setMaximo(float maximo) { this.maximo = maximo; }
}
package com.maze.models;

import com.google.gson.annotations.SerializedName;

public class RoomData {
    // Deve ser igual a 'Sala' no SELECT
    @SerializedName("Sala")
    private String room;

    // Deve ser igual a 'NumeroMarsamisEven' no SELECT
    @SerializedName("NumeroMarsamisEven")
    private String numberEven;

    // Deve ser igual a 'NumeroMarsamisOdd' no SELECT
    @SerializedName("NumeroMarsamisOdd")
    private String numberOdd;

    // Construtor vazio necessário para o GSON
    public RoomData() {
    }

    public RoomData(String room, String numberEven, String numberOdd) {
        this.room = room;
        this.numberEven = numberEven;
        this.numberOdd = numberOdd;
    }

    // Getters
    public String getRoom() { return room; }
    public String getNumberEven() { return numberEven; }
    public String getNumberOdd() { return numberOdd; }

    // Setters
    public void setRoom(String room) { this.room = room; }
    public void setNumberEven(String numberEven) { this.numberEven = numberEven; }
    public void setNumberOdd(String numberOdd) { this.numberOdd = numberOdd; }
}

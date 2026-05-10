package com.maze.models;

public class CorridorData {
    private String Room;
    private int NumberEven;
    private int NumberOdd;

    public CorridorData(String room, int numbereven, int numberodd) {
        Room = room;
        NumberEven = numbereven;
        NumberOdd = numberodd;
    }

    public String getRoom() { return Room; }
    public int getNumberEven() { return NumberEven; }
    public int getNumberOdd() { return NumberOdd; }

    public void setRoom(String room) { Room = room; }
    public void setNumberEven(int numberEven) { NumberEven = numberEven; }
    public void setNumberOdd(int numberOdd) { NumberOdd = numberOdd; }
}
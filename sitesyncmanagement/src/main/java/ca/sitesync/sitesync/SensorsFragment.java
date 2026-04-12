package ca.sitesync.sitesync;

import android.os.Bundle;

import androidx.fragment.app.Fragment;

import android.os.Handler;
import android.os.Looper;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.CheckBox;
import android.widget.TextView;

import com.google.firebase.firestore.DocumentReference;
import com.google.firebase.firestore.FirebaseFirestore;

/**
 * A simple {@link Fragment} subclass.
 * Use the {@link SensorsFragment#newInstance} factory method to
 * create an instance of this fragment.
 */
public class SensorsFragment extends Fragment {

    private CheckBox servoCheckbox;
    private CheckBox buzzerCheckbox;
    private CheckBox fingerprintCheckbox;

    FirebaseFirestore db = FirebaseFirestore.getInstance();
    @Override
    public View onCreateView(LayoutInflater inflater, ViewGroup container,
                             Bundle savedInstanceState) {
        // Inflate the layout for this fragment
        View view = inflater.inflate(R.layout.fragment_sensors, container, false);
        servoCheckbox = view.findViewById(R.id.ServoCheckbox);
        buzzerCheckbox = view.findViewById(R.id.BuzzerCheckbox);
        servoCheckbox.setOnCheckedChangeListener((buttonView, isChecked) -> {
            if (isChecked) {
                servotoggle();
            }
        });

        buzzerCheckbox.setOnCheckedChangeListener((buttonView, isChecked) -> {
            if (isChecked) {
                buzzertoggle();
            }
        });

        /*fingerprintCheckbox.setOnCheckedChangeListener((buttonView, isChecked) -> {
            if (isChecked) {
                fingerprinttoggle();
            }
        });*/
        return view;
    }
    private void buzzertoggle() {
        DocumentReference buzzerRef = db.collection("Devices").document("Buzzer1");
        //Turn buzzer on
        buzzerRef.update("buzzer", true);

        //Turn buzzer off
        new Handler(Looper.getMainLooper()).postDelayed(() -> {
            buzzerRef.update("buzzer", false);
        }, 1000); // 1 second delay
    }
    private void servotoggle() {
        DocumentReference buzzerRef = db.collection("Devices").document("Servo1");
        //Turn buzzer on
        buzzerRef.update("servo", true);

        //Turn buzzer off
        new Handler(Looper.getMainLooper()).postDelayed(() -> {
            buzzerRef.update("servo", false);
        }, 1000); // 1 second delay
    }
    /*private void fingerprinttoggle() {
        DocumentReference buzzerRef = db.collection("Devices").document("Fingerprint1");
        //Turn buzzer on
        buzzerRef.update("fingerprint", true);

        //Turn buzzer off
        new Handler(Looper.getMainLooper()).postDelayed(() -> {
            buzzerRef.update("fingerprint", false);
        }, 1000); // 1 second delay
    }*/

}